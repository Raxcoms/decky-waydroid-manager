from pathlib import Path
import os
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
from waydroid_manager.wayland import SurfaceCommits


def message(object_id, opcode, *values):
    body = struct.pack("=" + "I" * len(values), *values)
    return struct.pack("=II", object_id, ((len(body) + 8) << 16) | opcode) + body


def bind(object_id, interface):
    text = interface.encode() + b"\0"
    body = struct.pack("=II", object_id, len(text)) + text + b"\0" * (-len(text) % 4) + struct.pack("=II", 1, object_id)
    return struct.pack("=II", 2, (len(body) + 8) << 16) + body


def output_global(name):
    body = struct.pack("=II", name, 10) + b"wl_output\0\0\0" + struct.pack("=I", 4)
    return struct.pack("=II", 2, (len(body) + 8) << 16) + body


BOOTSTRAP = message(1, 1, 2) + bind(3, "wl_compositor") + message(3, 0, 4) + message(4, 6) + bind(5, "wp_presentation")
BUFFER = message(4, 1, 10, 0, 0) + message(4, 2, 0, 0, 1920, 1080) + message(4, 6)
FEEDBACK = message(5, 1, 4, 11)
EMPTY = message(4, 6)


class SurfaceCommitTests(unittest.TestCase):
    def setUp(self):
        self.protocol = SurfaceCommits()
        self.assertEqual(self.protocol.feed(BOOTSTRAP, [])[0], BOOTSTRAP)

    def test_feedback_applies_to_its_commit_and_only_a_trailing_empty_commit_is_dropped(self):
        result, fds = self.protocol.feed(BUFFER + FEEDBACK + EMPTY + EMPTY, [])
        self.assertEqual(result, BUFFER + FEEDBACK + EMPTY)
        self.assertEqual(fds, [])
        self.assertEqual(self.protocol.dropped, 1)

    def test_stream_fragmentation_does_not_change_filtering(self):
        stream = BUFFER + FEEDBACK + EMPTY + EMPTY
        for boundary in range(len(stream) + 1):
            protocol = SurfaceCommits()
            protocol.feed(BOOTSTRAP, [])
            first, _ = protocol.feed(stream[:boundary], [])
            second, _ = protocol.feed(stream[boundary:], [])
            self.assertEqual(first + second, BUFFER + FEEDBACK + EMPTY)

    def test_input_regions_callbacks_and_damage_still_commit(self):
        self.protocol.feed(BUFFER, [])
        for opcode, args in ((5, [0]), (3, [20]), (2, [0, 0, 10, 10])):
            with self.subTest(opcode=opcode):
                update = message(4, opcode, *args) + EMPTY
                self.assertEqual(self.protocol.feed(update, [])[0], update)

    def test_unmapping_and_initial_empty_commits_are_preserved(self):
        self.protocol.feed(BUFFER, [])
        unmap = message(4, 1, 0, 0, 0) + EMPTY + EMPTY
        self.assertEqual(self.protocol.feed(unmap, [])[0], unmap)

    def test_changed_region_contents_commit_even_when_id_is_unchanged(self):
        self.protocol.feed(BUFFER, [])
        create = message(3, 1, 7)
        initial = message(7, 1, 0, 0, 100, 100) + message(4, 5, 7) + EMPTY
        self.assertEqual(self.protocol.feed(create + initial, [])[0], create + initial)
        unchanged = message(4, 5, 7) + EMPTY
        self.assertEqual(self.protocol.feed(unchanged, [])[0], message(4, 5, 7))
        changed = message(7, 1, 100, 100, 100, 100) + message(4, 5, 7) + EMPTY
        self.assertEqual(self.protocol.feed(changed, [])[0], changed)

    def test_reusing_a_region_id_creates_an_independent_revision(self):
        create = message(3, 1, 7)
        assign = message(4, 5, 7) + EMPTY
        self.protocol.feed(BUFFER + create + message(7, 1, 0, 0, 20, 30) + assign, [])
        change = message(7, 0) + create + assign
        self.assertEqual(self.protocol.feed(change, [])[0], change)

    def test_synchronized_child_frame_keeps_its_parent_commit(self):
        create = bind(6, "wl_subcompositor") + message(3, 0, 7) + message(6, 1, 8, 7, 4)
        self.protocol.feed(BUFFER + create + EMPTY, [])
        child_frame = message(7, 1, 20, 0, 0) + message(7, 6)
        self.assertEqual(self.protocol.feed(child_frame + EMPTY, [])[0], child_frame + EMPTY)
        desync = message(8, 5)
        self.assertEqual(self.protocol.feed(desync + child_frame + EMPTY, [])[0], desync + child_frame)
        reposition = message(8, 1, 15, 5)
        self.assertEqual(self.protocol.feed(reposition + EMPTY, [])[0], reposition + EMPTY)
        self.assertEqual(self.protocol.feed(reposition + EMPTY, [])[0], reposition)
        self.protocol.feed(message(8, 4), [])
        self.assertEqual(self.protocol.feed(child_frame + EMPTY, [])[0], child_frame + EMPTY)
        destroy = message(8, 0)
        self.assertEqual(self.protocol.feed(destroy + EMPTY, [])[0], destroy)

    def test_viewport_on_desynchronized_child_does_not_duplicate_primary_frame(self):
        create = bind(6, "wl_subcompositor") + message(3, 0, 7) + message(6, 1, 8, 7, 4)
        create += message(8, 5) + bind(9, "wp_viewporter") + message(9, 1, 10, 7)
        self.protocol.feed(BUFFER + create + EMPTY, [])
        viewport = message(10, 1, 0, 0, 1024, 1024) + message(10, 2, 640, 640)
        child_frame = message(7, 1, 20, 0, 0) + viewport + message(7, 6)
        self.assertEqual(self.protocol.feed(child_frame + EMPTY, [])[0], child_frame)
        self.assertEqual(self.protocol.feed(viewport + message(7, 6), [])[0], viewport)
        resized = message(10, 2, 320, 320) + message(7, 6)
        self.assertEqual(self.protocol.feed(resized + EMPTY, [])[0], resized)
        reset = message(10, 0) + message(7, 6)
        self.assertEqual(self.protocol.feed(reset + EMPTY, [])[0], reset)

    def test_unknown_extensions_preserve_pending_state(self):
        self.protocol.feed(BUFFER, [])
        extension = message(99, 1, 4) + EMPTY
        self.assertEqual(self.protocol.feed(extension, [])[0], extension)

    def test_resetting_the_pointer_does_not_duplicate_the_main_surface(self):
        setup = bind(30, "wl_seat") + message(30, 0, 31)
        self.protocol.feed(setup + BUFFER, [])
        cursor = message(31, 0, 1, 0, 0, 0)
        self.assertEqual(self.protocol.feed(cursor + EMPTY, [])[0], cursor)

    def test_recycled_object_ids_do_not_keep_the_previous_interface(self):
        self.protocol.feed(bind(30, "wl_shm"), [])
        event = message(1, 1, 30)
        self.protocol.observe_server(event[:5])
        self.protocol.observe_server(event[5:])
        self.assertNotIn(30, self.protocol.objects)
        self.assertEqual(self.protocol.feed(message(30, 0), [])[0], message(30, 0))

    def test_game_resolution_updates_output_and_toplevel_without_changing_refresh_or_states(self):
        protocol = SurfaceCommits((1280, 720))
        setup = BOOTSTRAP + bind(30, "wl_output") + bind(31, "xdg_wm_base")
        setup += message(31, 2, 32, 4) + message(32, 1, 33)
        setup += bind(34, "zxdg_output_manager_v1") + message(34, 1, 35, 30)
        protocol.feed(setup, [])
        protocol.observe_server(output_global(1))
        stream = message(30, 1, 3, 1920, 1080, 120000) + message(30, 3, 2)
        stream += message(33, 0, 1920, 1080, 4, 2) + message(33, 2, 1920, 1080)
        stream += message(35, 1, 1920, 1080)
        expected = message(30, 1, 3, 1280, 720, 120000) + message(30, 3, 1)
        expected += message(33, 0, 1280, 720, 4, 2) + message(33, 2, 1280, 720)
        expected += message(35, 1, 1280, 720)
        for boundary in range(len(stream) + 1):
            with self.subTest(boundary=boundary):
                self.assertEqual(protocol.observe_server(stream[:boundary]) + protocol.observe_server(stream[boundary:]), expected)

    def test_multiple_native_outputs_keep_their_original_modes(self):
        protocol = SurfaceCommits((1280, 720))
        protocol.feed(BOOTSTRAP + bind(30, "wl_output") + bind(31, "wl_output"), [])
        protocol.observe_server(output_global(1) + output_global(2))
        events = message(30, 1, 3, 1920, 1080, 120000) + message(31, 1, 3, 1080, 1920, 60000)
        self.assertEqual(protocol.observe_server(events), events)

    def test_no_resolution_override_preserves_native_events(self):
        self.protocol.feed(bind(30, "wl_output"), [])
        event = message(30, 1, 3, 1920, 1080, 120000)
        self.assertEqual(self.protocol.observe_server(event), event)

    def test_fragmented_server_event_keeps_descriptors_until_it_can_be_forwarded(self):
        read_fd, write_fd = os.pipe()
        pending = os.dup(read_fd)
        try:
            self.protocol.feed(bind(30, "wl_output"), [])
            event = message(30, 1, 3, 1920, 1080, 120000)
            self.assertEqual(self.protocol.feed_server(event[:5], [pending]), (b"", []))
            self.assertEqual(self.protocol.feed_server(event[5:], []), (event, [pending]))
            os.close(pending)
            pending = os.dup(read_fd)
            self.protocol.feed_server(event[:5], [pending])
            self.protocol.close()
            with self.assertRaises(OSError):
                os.fstat(pending)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_unknown_object_lifetimes_disable_filtering_without_losing_bytes(self):
        self.protocol.feed(bind(30, "wl_shm"), [])
        stream = message(30, 0)
        self.assertEqual(self.protocol.feed(stream, [])[0], stream)
        self.assertFalse(self.protocol.enabled)
        self.assertEqual(self.protocol.feed(BUFFER + EMPTY, [])[0], BUFFER + EMPTY)

    def test_partial_message_descriptors_close_on_disconnect(self):
        read_fd, write_fd = os.pipe()
        pending = os.dup(read_fd)
        try:
            self.protocol.feed(BUFFER[:4], [pending])
            self.protocol.close()
            with self.assertRaises(OSError):
                os.fstat(pending)
        finally:
            os.close(read_fd)
            os.close(write_fd)
