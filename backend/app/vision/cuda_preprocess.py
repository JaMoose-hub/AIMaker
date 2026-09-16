"""Fused CUDA letterbox + BGR/HWC uint8 -> RGB/NCHW float32.

Only one original uint8 image crosses PCIe. The output stays on CUDA for
ORT I/O binding. Coordinate conventions and uint8 interpolation are those
of the existing OpenCV path (including its 2x area-resize optimization).
CuPy is optional outside the CUDA dependency group; failures are reported
by the locator and do not disable otherwise working CUDA inference.
"""
from __future__ import annotations

import numpy as np


_KERNEL = r'''
extern "C" __global__ void letterbox(
    const unsigned char* src, float* dst, int w, int h, int size,
    int ow, int oh, int left, int top)
{
    int i = blockDim.x * blockIdx.x + threadIdx.x;
    int plane = size * size;
    if (i >= 3 * plane) return;
    int c = 2 - i / plane, x = i % size - left;
    int y = (i % plane) / size - top;
    int value = 114;
    if (x >= 0 && x < ow && y >= 0 && y < oh) {
        float fx = (float)(((double)x + .5) * w / ow - .5);
        float fy = (float)(((double)y + .5) * h / oh - .5);
        int sx = (int)floorf(fx), sy = (int)floorf(fy);
        fx -= sx; fy -= sy;
        if (sx < 0) { sx = 0; fx = 0; }
        if (sx >= w - 1) { sx = w - 1; fx = 0; }
        int sx1 = min(sx + 1, w - 1);
        int sy0 = max(0, min(sy, h - 1)), sy1 = max(0, min(sy + 1, h - 1));
        int a0 = __float2int_rn((1.f - fx) * 2048.f);
        int a1 = __float2int_rn(fx * 2048.f);
        int b0 = __float2int_rn((1.f - fy) * 2048.f);
        int b1 = __float2int_rn(fy * 2048.f);
        int p00 = src[(sy0 * w + sx) * 3 + c];
        int p01 = src[(sy0 * w + sx1) * 3 + c];
        int p10 = src[(sy1 * w + sx) * 3 + c];
        int p11 = src[(sy1 * w + sx1) * 3 + c];
        if (w == ow * 2 && h == oh * 2) {
            value = (p00 + p01 + p10 + p11 + 2) >> 2;
        } else {
            int row0 = p00 * a0 + p01 * a1;
            int row1 = p10 * a0 + p11 * a1;
            value = (((b0 * (row0 >> 4)) >> 16) +
                     ((b1 * (row1 >> 4)) >> 16) + 2) >> 2;
        }
    }
    dst[i] = value * (1.f / 255.f);
}
'''


class CudaPreprocessor:
    """Owned by one locator/worker; buffers are reused, never shared mutable."""
    def __init__(self, size: int, device_id: int):
        import cupy as cp
        self.cp = cp
        self.size = int(size)
        self.device_id = int(device_id)
        self.input = None
        with cp.cuda.Device(self.device_id):
            # Non-blocking isolates four model workers. Synchronize explicitly
            # before handing its pointer to ORT's independently owned stream.
            self.stream = cp.cuda.Stream(non_blocking=True)
            self.output = cp.empty((1, 3, self.size, self.size), dtype=cp.float32)
            self.kernel = cp.RawKernel(_KERNEL, 'letterbox', options=('--fmad=false',))
            self.kernel.compile()

    def prepare(self, frame):
        if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
            raise ValueError('CUDA preprocessing requires a uint8 BGR image')
        h, w = frame.shape[:2]
        scale = min(self.size / w, self.size / h)
        ow, oh = max(1, round(w * scale)), max(1, round(h * scale))
        left, top = (self.size - ow) // 2, (self.size - oh) // 2
        cp = self.cp
        with cp.cuda.Device(self.device_id), self.stream:
            if self.input is None or self.input.shape != frame.shape:
                self.input = cp.empty(frame.shape, dtype=cp.uint8)
            self.input.set(np.ascontiguousarray(frame), stream=self.stream)
            n = 3 * self.size * self.size
            self.kernel(((n + 255) // 256,), (256,),
                        (self.input, self.output, np.int32(w), np.int32(h),
                         np.int32(self.size), np.int32(ow), np.int32(oh),
                         np.int32(left), np.int32(top)))
            self.stream.synchronize()
        return self.output, scale, float(left), float(top)
