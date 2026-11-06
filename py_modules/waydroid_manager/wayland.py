from dataclasses import dataclass, field
import os
import struct
import sys


@dataclass
class Surface:
    has_buffer: bool = False
    dirty: bool = True
    state: dict = field(default_factory=dict)


class SurfaceCommits:
    def __init__(self, resolution: tuple[int, int] | None = None):
        self.pending = bytearray()
        self.events = bytearray()
        self.fds: list[int] = []
        self.server_fds: list[int] = []
        self.resolution = resolution
        self.objects = {1: "wl_display"}
        self.surfaces: dict[int, Surface] = {}
        self.xdg_surfaces: dict[int, int] = {}
        self.regions: dict[int, list[tuple[int, bytes]]] = {}
        self.dropped = 0
        self.commits = 0
        self.enabled = True

    def observe_server(self, data: bytes) -> bytes:
        self.events.extend(data)
        offset = 0
        messages = []
        while len(self.events) - offset >= 8:
            object_id, header = struct.unpack_from("=II", self.events, offset)
            size, opcode = header >> 16, header & 65535
            if size < 8 or size % 4:
                raise OSError("Invalid Wayland event size")
            if len(self.events) - offset < size:
                break
            if object_id == 1 and opcode == 1 and size == 12:
                deleted = struct.unpack_from("=I", self.events, offset + 8)[0]
                self.objects.pop(deleted, None)
            elif self.objects.get(object_id) == "zwp_linux_buffer_params_v1" and opcode == 0 and size == 12:
                self.objects[struct.unpack_from("=I", self.events, offset + 8)[0]] = "wl_buffer"
            message = bytearray(self.events[offset:offset + size])
            if self.resolution and self.enabled:
                kind = self.objects.get(object_id)
                # Steam sets the game mode on its inherited Xwayland display, not the native output.
                if kind == "wl_output" and opcode == 1 and size == 24:
                    struct.pack_into("=ii", message, 12, *self.resolution)
                elif kind == "wl_output" and opcode == 3 and size == 12:
                    struct.pack_into("=i", message, 8, 1)
                elif (kind == "xdg_toplevel" and opcode in (0, 2) and size >= 16) or (kind == "zxdg_output_v1" and opcode == 1 and size == 16):
                    struct.pack_into("=ii", message, 8, *self.resolution)
            messages.append(message)
            offset += size
        del self.events[:offset]
        return b"".join(messages)

    def feed_server(self, data: bytes, fds: list[int]) -> tuple[bytes, list[int]]:
        self.server_fds.extend(fds)
        output = self.observe_server(data)
        if not output:
            return b"", []
        descriptors, self.server_fds = self.server_fds, []
        return output, descriptors

    def keep(self, message: bytes) -> bool:
        object_id, header = struct.unpack_from("=II", message)
        opcode = header & 65535
        body = message[8:]
        kind = self.objects.get(object_id)
        if kind == "wl_display" and opcode == 1:
            self.objects[struct.unpack_from("=I", body)[0]] = "wl_registry"
        elif kind == "wl_registry" and opcode == 0:
            length = struct.unpack_from("=I", body, 4)[0]
            name = body[8:8 + length - 1].decode()
            new_id = struct.unpack_from("=I", body, 12 + (length + 3) // 4 * 4)[0]
            self.objects[new_id] = name
        elif kind == "wl_compositor":
            new_id = struct.unpack_from("=I", body)[0]
            self.objects[new_id] = "wl_surface" if opcode == 0 else "wl_region"
            if opcode == 0:
                self.surfaces[new_id] = Surface()
            else:
                self.regions[new_id] = []
        elif kind == "wl_surface":
            surface = self.surfaces[object_id]
            if opcode == 0:
                self.surfaces.pop(object_id)
                self.objects.pop(object_id, None)
            elif opcode == 6:
                self.commits += 1
                # Waydroid follows each buffer commit with an empty commit.
                # Leave its presentation feedback queued for the next buffer.
                if surface.has_buffer and not surface.dirty:
                    self.dropped += 1
                    return False
                surface.dirty = False
            else:
                if opcode in (4, 5):
                    region = struct.unpack_from("=I", body)[0]
                    value = tuple(self.regions[region]) if region else None
                elif opcode in (7, 8, 10):
                    value = body
                else:
                    value = None
                if opcode not in (4, 5, 7, 8, 10) or opcode not in surface.state or surface.state[opcode] != value:
                    surface.dirty = True
                surface.state[opcode] = value
                if opcode == 1:
                    surface.has_buffer = struct.unpack_from("=I", body)[0] != 0
        elif kind == "wl_region":
            if opcode == 0:
                self.regions.pop(object_id, None)
                self.objects.pop(object_id, None)
            else:
                self.regions[object_id].append((opcode, body))
        elif kind == "wl_seat" and opcode in (0, 1, 2):
            self.objects[struct.unpack_from("=I", body)[0]] = ("wl_pointer", "wl_keyboard", "wl_touch")[opcode]
        elif kind == "wl_shm" and opcode == 0:
            self.objects[struct.unpack_from("=I", body)[0]] = "wl_shm_pool"
        elif kind == "wl_shm_pool" and opcode == 0:
            self.objects[struct.unpack_from("=I", body)[0]] = "wl_buffer"
        elif kind == "zwp_linux_dmabuf_v1" and opcode == 1:
            self.objects[struct.unpack_from("=I", body)[0]] = "zwp_linux_buffer_params_v1"
        elif kind == "zwp_linux_buffer_params_v1" and opcode == 3:
            self.objects[struct.unpack_from("=I", body)[0]] = "wl_buffer"
        elif kind == "wl_drm" and opcode in (1, 2, 3):
            self.objects[struct.unpack_from("=I", body)[0]] = "wl_buffer"
        elif kind == "xdg_wm_base" and opcode == 2:
            new_id, surface_id = struct.unpack_from("=II", body)
            self.objects[new_id] = "xdg_surface"
            self.xdg_surfaces[new_id] = surface_id
        elif kind == "xdg_surface":
            if opcode == 0:
                self.xdg_surfaces.pop(object_id, None)
                self.objects.pop(object_id, None)
            elif opcode in (1, 2):
                self.objects[struct.unpack_from("=I", body)[0]] = "xdg_toplevel" if opcode == 1 else "xdg_popup"
            elif opcode in (3, 4):
                surface = self.surfaces.get(self.xdg_surfaces[object_id])
                if surface:
                    if opcode == 4 or surface.state.get("geometry") != body:
                        surface.dirty = True
                    if opcode == 3:
                        surface.state["geometry"] = body
        elif kind == "zxdg_output_manager_v1" and opcode == 1:
            self.objects[struct.unpack_from("=I", body)[0]] = "zxdg_output_v1"
        elif kind not in {"wl_display", "wl_registry", "wp_presentation", "wl_region", "wl_seat", "wl_pointer", "wl_keyboard", "wl_touch", "wl_buffer", "wl_shm", "wl_shm_pool", "zwp_linux_dmabuf_v1", "zwp_linux_buffer_params_v1"}:
            # Unknown extensions may add pending surface state.
            for surface in self.surfaces.values():
                surface.dirty = True
        return True

    def feed(self, data: bytes, fds: list[int]) -> tuple[bytes, list[int]]:
        if not self.enabled:
            return data, fds
        self.pending.extend(data)
        self.fds.extend(fds)
        messages = []
        offset = 0
        try:
            while len(self.pending) - offset >= 8:
                _, header = struct.unpack_from("=II", self.pending, offset)
                size = header >> 16
                if size < 8 or size % 4:
                    raise OSError("Invalid Wayland message size")
                if len(self.pending) - offset < size:
                    break
                message = bytes(self.pending[offset:offset + size])
                if self.keep(message):
                    messages.append(message)
                offset += size
        except (ValueError, KeyError, struct.error) as error:
            # Unknown object lifetimes must not disconnect a valid client.
            object_id, header = struct.unpack_from("=II", message)
            print(f"Commit filtering disabled for {self.objects.get(object_id)} object {object_id}, opcode {header & 65535}: {error}", file=sys.stderr, flush=True)
            self.enabled = False
            data, descriptors = bytes(self.pending), self.fds
            self.pending.clear()
            self.fds = []
            return data, descriptors
        del self.pending[:offset]
        if not messages:
            return b"", []
        descriptors, self.fds = self.fds, []
        return b"".join(messages), descriptors

    def close(self) -> None:
        for fd in self.fds + self.server_fds:
            os.close(fd)
        self.fds.clear()
        self.server_fds.clear()
