import assert from "node:assert/strict";
import { test } from "node:test";
import {
  fitRect,
  draftStorageKey,
  freezeInheritedMedia,
  inheritedMediaLabel,
  mergeConversation,
  normalizeBase,
  parsePairingQr,
  photoImageMatches,
  previewLease,
  reliablePose,
  requiresJpegConversion,
  validateAttachments,
} from "../src/domain";
import type { Capture, Conversation, LocalAsset } from "../src/types";
test("draft recovery identity survives a new session and isolates another project or computer", () => {
  const original = draftStorageKey("http://192.168.1.2:8000", "conversation-1");
  assert.equal(
    original,
    draftStorageKey("http://192.168.1.2:8000/", "conversation-1"),
  );
  assert.notEqual(
    original,
    draftStorageKey("http://192.168.1.2:8000", "conversation-2"),
  );
  assert.notEqual(
    original,
    draftStorageKey("http://192.168.1.3:8000", "conversation-1"),
  );
  assert.ok(!draftStorageKey("http://192.168.1.2:8000", "../x").includes("/"));
});
test("queued text freezes the visible media or explicit absence before later media changes", () => {
  const conversation: Conversation = {
    id: "c",
    messages: [],
    jobs: [],
    before: null,
    total: 0,
    context_epoch: 2,
    round: 1,
    active_media: {
      asset_ids: ["photo-a"],
      capture_id: "capture-a",
      epoch: 2,
      round: 1,
      attachments: [
        {
          id: "photo-a",
          type: "image",
          mime: "image/jpeg",
          url: "/a",
          size: 10,
          filename: "a.jpg",
        },
      ],
    },
  };
  const frozen = freezeInheritedMedia(conversation, 0, null, 1);
  conversation.active_media!.asset_ids[0] = "photo-b";
  conversation.active_media!.capture_id = "capture-b";
  assert.deepEqual(frozen, {
    asset_ids: ["photo-a"],
    capture_id: "capture-a",
    inherit_media: false,
  });
  assert.deepEqual(freezeInheritedMedia(null, 0, null, 1), {
    asset_ids: [],
    inherit_media: false,
  });
  assert.deepEqual(freezeInheritedMedia(conversation, 1, null, 1), {
    asset_ids: [],
    inherit_media: false,
  });
  assert.deepEqual(
    freezeInheritedMedia(conversation, 0, "explicit-capture", 1),
    { asset_ids: [], inherit_media: false },
  );
});
test("inherited media label follows active context and newest finalized photo; new attachments override", () => {
  const asset = {
    id: "a",
    type: "image" as const,
    mime: "image/jpeg",
    url: "/a",
    size: 20,
    filename: "previous.jpg",
  };
  const old: Conversation = {
    id: "c",
    messages: [],
    jobs: [],
    before: null,
    total: 0,
    context_epoch: 2,
    round: 1,
    active_media: {
      asset_ids: ["a"],
      attachments: [asset],
      epoch: 2,
      round: 1,
    },
  };
  assert.match(inheritedMediaLabel(old, 0, null)!, /previous.jpg/);
  assert.equal(inheritedMediaLabel(old, 1, null), null);
  assert.equal(inheritedMediaLabel(old, 0, "explicit-old-photo"), null);
  assert.equal(
    inheritedMediaLabel({ ...old, context_epoch: 3 }, 0, null),
    null,
  );
  assert.equal(inheritedMediaLabel({ ...old, round: 2 }, 0, null), null);
  assert.equal(inheritedMediaLabel(old, 0, null, 2), null);
  assert.match(
    inheritedMediaLabel({ ...old, round: 0 }, 0, null, 1)!,
    /previous.jpg/,
  );
  assert.match(
    inheritedMediaLabel(
      {
        ...old,
        active_media: {
          ...old.active_media!,
          attachments: [
            { ...asset, type: "video", filename: "demo.mp4", duration: 12.3 },
          ],
        },
      },
      0,
      null,
      1,
    )!,
    /最近影片.*demo.mp4.*12.3 秒/,
  );
  assert.equal(
    inheritedMediaLabel({ ...old, active_media: null }, 0, null),
    null,
  );
  const next = mergeConversation(old, {
    ...old,
    active_media: {
      asset_ids: ["b"],
      capture_id: "new-capture",
      attachments: [{ ...asset, id: "b", filename: "new-gpio.jpg" }],
      epoch: 2,
      round: 1,
    },
  });
  assert.match(
    inheritedMediaLabel(next, 0, null)!,
    /最近定位照片.*new-gpio.jpg/,
  );
  assert.doesNotMatch(inheritedMediaLabel(next, 0, null)!, /previous.jpg/);
});
test("loaded photograph must match native geometry dimensions, including orientation", () => {
  assert.equal(photoImageMatches([1920, 1080], 1920, 1080), true);
  assert.equal(photoImageMatches([1920, 1080], 1080, 1920), false);
  assert.equal(photoImageMatches([1920, 1080], 960, 540), false);
  assert.equal(photoImageMatches([1920, 1080], NaN, 1080), false);
});
test("same preview polling never extends lock TTL, new frame can renew", () => {
  const now = 1800000000000;
  const status = {
    generation: 3,
    preview_seq: 5,
    can_capture: true,
    valid_for_ms: 1500,
    expires_at: (now + 1500) / 1000,
  };
  const first = previewLease(status, now, { key: "", deadline: 0 });
  assert.equal(first.deadline, now + 1500);
  assert.equal(previewLease(status, now + 900, first).deadline, now + 1500);
  assert.equal(previewLease(status, now + 2000, first).deadline, now + 1500);
  assert.equal(
    previewLease(
      { ...status, preview_seq: 6, expires_at: (now + 2500) / 1000 },
      now + 1000,
      first,
    ).deadline,
    now + 2500,
  );
  assert.equal(
    previewLease({ ...status, can_capture: false }, now + 1000, first).deadline,
    0,
  );
});
const image: LocalAsset = {
  upload_id: "a",
  uri: "file:///a.jpg",
  name: "a.jpg",
  mime: "image/jpeg",
  type: "image",
  size: 100,
  width: 1920,
  height: 1080,
};
test("HEIC gallery fallback requires a real conversion, preserving normal image and video paths", () => {
  assert.equal(requiresJpegConversion(image), false);
  assert.equal(requiresJpegConversion({ ...image, mime: "image/heic" }), true);
  assert.equal(
    requiresJpegConversion({ ...image, mime: "", name: "IMG_0001.HEIF" }),
    true,
  );
  assert.equal(
    requiresJpegConversion({ ...image, uri: "file:///tmp/image.avif" }),
    true,
  );
  assert.equal(
    requiresJpegConversion({ ...image, mime: "image/png", name: "a.png" }),
    false,
  );
  assert.equal(
    requiresJpegConversion({
      ...image,
      type: "video",
      mime: "video/quicktime",
      name: "a.mov",
    }),
    false,
  );
});
test("pairing validates QR protocol and strips API suffix", () => {
  assert.deepEqual(
    parsePairingQr(
      JSON.stringify({
        type: "tinkro-mobile",
        base_url: "http://192.168.1.1:8000/api/mobile",
        code: " A1 ",
      }),
    ),
    { base_url: "http://192.168.1.1:8000", code: "A1" },
  );
  assert.throws(() => normalizeBase("file:///etc/x"));
  assert.throws(() => parsePairingQr('{"type":"other"}'));
  assert.throws(() => normalizeBase("https://user:pass@example.com"));
});
test("attachments enforce mutually exclusive limits and video duration/bytes", () => {
  assert.equal(validateAttachments([image, image, image, image]), null);
  assert.ok(validateAttachments([image, image, image, image, image]));
  const video = {
    ...image,
    type: "video" as const,
    duration: 60,
    size: 200 * 1024 * 1024,
  };
  assert.equal(validateAttachments([video]), null);
  assert.ok(validateAttachments([video, image]));
  assert.ok(validateAttachments([{ ...video, duration: 60.1 }]));
  assert.ok(validateAttachments([{ ...video, size: video.size + 1 }]));
  assert.ok(validateAttachments([{ ...video, duration: undefined }]));
});
test("poll merge keeps older pages and replaces repeated messages without duplicating", () => {
  const initial: Conversation = {
    id: "c",
    messages: [{ id: "a", role: "user", text: "old", created_at: 1 }],
    jobs: [],
    before: 0,
    total: 2,
  };
  const result = mergeConversation(initial, {
    ...initial,
    messages: [
      { id: "a", role: "user", text: "updated", created_at: 1 },
      { id: "b", role: "assistant", text: "reply", created_at: 2 },
    ],
    before: 1,
  });
  assert.equal(result.messages.length, 2);
  assert.equal(result.messages[0].text, "updated");
  assert.equal(result.before, 0);
  assert.equal(
    mergeConversation(result, { ...initial, id: "other" }).messages.length,
    1,
  );
});
test("contained overlay preserves aspect and centers portrait and landscape images", () => {
  assert.deepEqual(fitRect([2000, 1000], [400, 400]), {
    width: 400,
    height: 200,
    x: 0,
    y: 100,
    scale: 0.2,
  });
  assert.deepEqual(fitRect([1000, 2000], [400, 400]), {
    width: 200,
    height: 400,
    x: 100,
    y: 0,
    scale: 0.2,
  });
});
test("photo pins require current frame and validated geometry, never model lock alone", () => {
  const pose = {
    board_id: "raspberry-pi-5",
    frame_id: 2,
    video_size: [1920, 1080] as [number, number],
    tracking: "locked",
    pins: [],
    outline: null,
  };
  const c = {
    capture_id: "x",
    session_id: "s",
    image_url: "/x",
    frame_id: 2,
    video_size: pose.video_size,
    detection: pose,
    components: [],
    wires: [],
  } satisfies Capture;
  assert.equal(reliablePose(c, pose), false);
  const verified = {
    ...c,
    localization: [
      {
        object_id: "raspberry-pi-5",
        status: "located",
        raw_outline_px: null,
        corrected_outline_px: null,
        evidence: {
          board_geometry_verified: true,
          pin_geometry_verified: true,
        },
      },
    ],
  };
  assert.equal(reliablePose(verified, pose), true);
  assert.equal(reliablePose({ ...verified, stale: true }, pose), false);
  assert.equal(reliablePose(verified, { ...pose, frame_id: 1 }), false);
});
