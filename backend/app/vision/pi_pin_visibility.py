"""Display projected Pi GPIO; appearance change alone is not occlusion.

Partial board support plus local appearance loss is suspected obstruction.
Require three consecutive frames for hiding or recovery. The caller still
enforces whole-pose validity, lease and image bounds.
"""


class PiPinVisibility:
    def __init__(self):
        self.states = {}

    def supported(self, pins, regions, partial):
        visible = set()
        for pin in pins:
            key = pin['id']
            hidden, pending, count = self.states.get(key, (False, None, 0))
            suspect = bool(partial and not regions.get(key, {}).get('supported', False))
            if suspect == hidden:
                pending, count = None, 0
            else:
                count = count + 1 if pending == suspect else 1
                pending = suspect
                if count >= 3:
                    hidden, pending, count = suspect, None, 0
            self.states[key] = hidden, pending, count
            if not hidden:
                visible.add(key)
        return visible
