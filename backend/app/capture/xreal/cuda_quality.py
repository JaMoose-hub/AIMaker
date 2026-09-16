"""Eye-only CUDA port of the native-resolution CLEAN filter in quality.py.

The filter parameters and motion rules match the existing CPU algorithm; the
CUDA bilateral rounding can differ by one 8-bit channel level. No inference
model or OpenCV process setting is changed here. Capture protocol provenance
and retained upstream license notices are documented in this package's NOTICE.
CuPy is optional and imported only when an Eye CLEAN frame needs processing.
"""
from __future__ import annotations
import logging

import numpy as np

from .quality import RgbDenoiser

log = logging.getLogger(__name__)

CUDA_SOURCE = r'''
__device__ __forceinline__ int reflect101(int x, int n) {
    return x < 0 ? -x : (x >= n ? 2*n-x-2 : x);
}
__device__ __forceinline__ unsigned char sat(int value) {
    return (unsigned char)max(0,min(255,value));
}
extern "C" __global__ void bgr_to_ycc(const unsigned char* src, unsigned char* dst, int n) {
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i>=n) return;
    int b=src[3*i], g=src[3*i+1], r=src[3*i+2];
    int y=(b*1868+g*9617+r*4899+8192)>>14;
    dst[3*i]=sat(y);
    dst[3*i+1]=sat(((r-y)*11682+(128<<14)+8192)>>14);
    dst[3*i+2]=sat(((b-y)*9241+(128<<14)+8192)>>14);
}
extern "C" __global__ void spatial(
    const unsigned char* src, unsigned char* filtered, const float* range_weight,
    int w,int h) {
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i>=w*h) return;
    int x=i%w,y=i/w;
    // OpenCV's uint8 bit-exact 3-tap Gaussian coefficients, scale256:
    // sigma0.8 -> [61,134,61]; sigma0.7 -> [54,148,54].
    int motion=0,cr=0,cb=0;
    #pragma unroll
    for(int dy=-1;dy<=1;dy++) {
        int yy=reflect101(y+dy,h), my=dy==0?134:61, cy=dy==0?148:54;
        #pragma unroll
        for(int dx=-1;dx<=1;dx++) {
            int q=(yy*w+reflect101(x+dx,w))*3;
            int mw=my*(dx==0?134:61),cw=cy*(dx==0?148:54);
            motion+=src[q]*mw;cr+=src[q+1]*cw;cb+=src[q+2]*cw;
        }
    }
    int center=src[i*3];
    float sum=(float)center,total=1.f;
    const int dxs[4]={0,-1,1,0}, dys[4]={-1,0,0,1};
    #pragma unroll
    for(int k=0;k<4;k++) {
        int value=src[(reflect101(y+dys[k],h)*w+reflect101(x+dxs[k],w))*3];
        float weight=range_weight[abs(value-center)]*.4578333617716143f;
        sum+=value*weight;total+=weight;
    }
    filtered[4*i]=sat(__float2int_rn(sum/total));
    filtered[4*i+1]=sat((cr+32768)>>16);
    filtered[4*i+2]=sat((cb+32768)>>16);
    filtered[4*i+3]=sat((motion+32768)>>16);
}
extern "C" __global__ void temporal_to_bgr(
    const unsigned char* current,const unsigned char* previous,unsigned char* history,
    unsigned char* output,unsigned char* moving_mask,int w,int h,int first) {
    int i=blockDim.x*blockIdx.x+threadIdx.x;
    if(i>=w*h) return;
    int x=i%w,y=i/w;
    bool moving=false;
    if(!first) {
        // OpenCV dilation's default constant border contributes zero here.
        #pragma unroll
        for(int dy=-1;dy<=1;dy++) {
            #pragma unroll
            for(int dx=-1;dx<=1;dx++) {
                int xx=x+dx,yy=y+dy;
                if(xx<0||yy<0||xx>=w||yy>=h) continue;
                int q=(yy*w+xx)*4;
                moving= moving || abs((int)current[q+3]-(int)previous[q+3])>3
                    || abs((int)current[q+1]-(int)previous[q+1])>8
                    || abs((int)current[q+2]-(int)previous[q+2])>8;
            }
        }
    }
    moving_mask[i]=moving?255:0;
    int values[3];
    #pragma unroll
    for(int c=0;c<3;c++) {
        int value=current[4*i+c];
        if(!first&&!moving) value=(3*value+2*(int)history[3*i+c]+2)/5;
        history[3*i+c]=(unsigned char)value;values[c]=value;
    }
    int y0=values[0],cr=values[1]-128,cb=values[2]-128;
    output[3*i]=sat(y0+((cb*29049+8192)>>14));
    output[3*i+1]=sat(y0+((cr*-11698+cb*-5636+8192)>>14));
    output[3*i+2]=sat(y0+((cr*22987+8192)>>14));
}
'''


class CudaFastClean:
    """One Eye session's CUDA buffers, stream, and temporal history.

    A dedicated pool makes close() release only this filter's allocations.
    Models and other CuPy clients keep their own pools and streams intact.
    """

    _BUFFER_NAMES = ("input", "ycc", "current", "previous", "history",
                     "output", "mask", "weights")

    def __init__(self, device_id: int = 0, *, collect_motion_fraction: bool = True):
        import cupy as cp

        self.cp, self.device_id = cp, int(device_id)
        self.collect_motion_fraction = bool(collect_motion_fraction)
        self.shape = None
        self.first = True
        self.last_motion_fraction = 0.0 if self.collect_motion_fraction else None
        self.stream = self.pool = None
        self.kernels = {}
        self._closed = False
        try:
            if cp.cuda.runtime.getDeviceCount() <= self.device_id:
                raise RuntimeError("No CUDA device is available for Eye denoising")
            with cp.cuda.Device(self.device_id):
                self.pool = cp.cuda.MemoryPool()
                self.stream = cp.cuda.Stream(non_blocking=True)
                with self.stream, cp.cuda.using_allocator(self.pool.malloc):
                    self.kernels = {
                        name: cp.RawKernel(CUDA_SOURCE, name, options=("--fmad=false",))
                        for name in ("bgr_to_ycc", "spatial", "temporal_to_bgr")
                    }
                    for kernel in self.kernels.values():
                        kernel.compile()
                    weights = np.exp(-np.arange(256, dtype=np.float64) ** 2 / 98.)
                    self.weights = cp.asarray(weights.astype(np.float32))
                self.stream.synchronize()
        except Exception:
            self.close()
            raise

    def reset(self):
        self.first = True
        self.last_motion_fraction = 0.0 if self.collect_motion_fraction else None

    def process(self, frame):
        if self._closed:
            raise RuntimeError("Eye CUDA denoiser is closed")
        if (frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3
                or min(frame.shape[:2]) < 2):
            raise ValueError("Expected uint8 BGR image at least 2 by 2 pixels")
        cp = self.cp
        height, width = frame.shape[:2]
        n = height * width
        with (cp.cuda.Device(self.device_id), self.stream,
              cp.cuda.using_allocator(self.pool.malloc)):
            if self.shape != frame.shape:
                self.shape = frame.shape
                self.input = cp.empty(frame.shape, cp.uint8)
                self.ycc = cp.empty(frame.shape, cp.uint8)
                self.current = cp.empty((height, width, 4), cp.uint8)
                self.previous = cp.empty_like(self.current)
                self.history = cp.empty(frame.shape, cp.uint8)
                self.output = cp.empty(frame.shape, cp.uint8)
                self.mask = cp.empty((height, width), cp.uint8)
                self.first = True
            self.input.set(np.ascontiguousarray(frame), stream=self.stream)
            launch = ((n + 255) // 256,)
            self.kernels["bgr_to_ycc"](launch, (256,), (self.input, self.ycc, np.int32(n)))
            self.kernels["spatial"](launch, (256,), (
                self.ycc, self.current, self.weights, np.int32(width), np.int32(height)))
            self.kernels["temporal_to_bgr"](launch, (256,), (
                self.current, self.previous, self.history, self.output, self.mask,
                np.int32(width), np.int32(height), np.int32(self.first)))
            motion_count = cp.count_nonzero(self.mask) if self.collect_motion_fraction else None
            # get() returns independent host storage. FrameBus and JPEG retain
            # the same image even when the next frame reuses device buffers.
            result = self.output.get(stream=self.stream, blocking=True)
            self.last_motion_fraction = (
                int(motion_count.get(stream=self.stream)) / n
                if motion_count is not None else None
            )
            self.current, self.previous = self.previous, self.current
            self.first = False
            # The blocking image download already completes the pixel/history
            # kernels. Production Eye does not need another scalar download or
            # synchronization for an unused diagnostic.
            if self.collect_motion_fraction:
                self.stream.synchronize()
            return result

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            with self.cp.cuda.Device(self.device_id):
                try:
                    if self.stream is not None:
                        self.stream.synchronize()
                finally:
                    for name in self._BUFFER_NAMES:
                        if hasattr(self, name):
                            setattr(self, name, None)
                    self.kernels = {}
                    if self.pool is not None:
                        self.pool.free_all_blocks()
        finally:
            self.stream = self.pool = None
            self.shape = None


class EyeDenoiser:
    """Lazily select CUDA for CLEAN and fall back once to fresh CPU history."""

    def __init__(self, mode: str = "clean", *, collect_motion_fraction: bool = True):
        self.mode = mode
        self.collect_motion_fraction = bool(collect_motion_fraction)
        self._cpu = RgbDenoiser(mode)
        self._cuda = None
        self._cuda_attempted = mode != "clean"
        self._closed = False
        self.backend = "pending" if mode == "clean" else ("none" if mode == "original" else "cpu")
        self.fallback_reason = None
        self.last_motion_fraction = 0.0 if self.collect_motion_fraction else None

    def _fallback(self, exc):
        self.fallback_reason = f"{type(exc).__name__}: {exc}"
        log.warning("Eye CLEAN using CPU fallback: %s", self.fallback_reason)
        self._close_cuda()
        # Never combine a previous CPU session (or failed CUDA output) with the
        # current frame. This frame becomes the new temporal history seed.
        self._cpu = RgbDenoiser(self.mode)
        self.backend = "cpu"

    def _close_cuda(self):
        current, self._cuda = self._cuda, None
        if current is not None:
            try:
                current.close()
            except Exception:
                log.warning("Could not release Eye CUDA filter cleanly", exc_info=True)

    def reset(self):
        self._cpu.reset()
        if self._cuda is not None:
            self._cuda.reset()
        self.last_motion_fraction = 0.0 if self.collect_motion_fraction else None

    def process(self, frame):
        if self._closed:
            raise RuntimeError("Eye denoiser is closed")
        if not self._cuda_attempted:
            self._cuda_attempted = True
            try:
                self._cuda = CudaFastClean(collect_motion_fraction=self.collect_motion_fraction)
                self.backend = "cuda"
            except Exception as exc:
                self._fallback(exc)
        if self._cuda is not None:
            try:
                result = self._cuda.process(frame)
                self.last_motion_fraction = (
                    self._cuda.last_motion_fraction if self.collect_motion_fraction else None
                )
                return result
            except Exception as exc:
                self._fallback(exc)
        result = self._cpu.process(frame)
        self.last_motion_fraction = self._cpu.last_motion_fraction if self.collect_motion_fraction else None
        return result

    def close(self):
        if not self._closed:
            self._closed = True
            self._close_cuda()
            self._cpu.reset()


def create_eye_denoiser(mode: str = "clean") -> EyeDenoiser:
    """Live Eye needs filtered pixels, not an aggregate motion diagnostic."""
    return EyeDenoiser(mode, collect_motion_fraction=False)
