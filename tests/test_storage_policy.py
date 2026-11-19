from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "A Java compiler is needed")
class StoragePolicyTests(unittest.TestCase):
    def test_fixed_entries_reject_mutations_while_contents_remain_mutable(self):
        source = Path(__file__).resolve().parents[1] / "android/storage/src/waydroid/manager/storage/SharePolicy.java"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            harness = root / "CheckPolicy.java"
            harness.write_text('''import waydroid.manager.storage.SharePolicy;
import java.io.FileNotFoundException;
public class CheckPolicy {
  public static void main(String[] args) throws Exception {
    for (String id : new String[]{"host", "host/Home", "host/Drive", "host/Another drive"}) {
      try { SharePolicy.requireMutable(id); throw new AssertionError(id); }
      catch (FileNotFoundException expected) { }
    }
    for (String id : new String[]{"host/Home/file.txt", "host/Drive/folder", "host/Drive/folder/file.txt"})
      SharePolicy.requireMutable(id);
    for (String id : new String[]{"other/Home/file", "host/Home/../Drive", "host/Home//file", "host/Home/./file"}) {
      try { SharePolicy.relative(id); throw new AssertionError(id); }
      catch (FileNotFoundException expected) { }
    }
  }
}''')
            subprocess.run(["javac", "-d", str(root), str(source), str(harness)], check=True)
            subprocess.run(["java", "-cp", str(root), "CheckPolicy"], check=True)
