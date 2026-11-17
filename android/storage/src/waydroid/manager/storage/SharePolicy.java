package waydroid.manager.storage;

import java.io.FileNotFoundException;

public final class SharePolicy {
    public static final String ROOT = "host";

    public static String relative(String documentId) throws FileNotFoundException {
        if (ROOT.equals(documentId)) return "";
        if (documentId == null || !documentId.startsWith(ROOT + "/"))
            throw new FileNotFoundException("Invalid Host document");
        String path = documentId.substring(ROOT.length() + 1);
        for (String component : path.split("/", -1)) {
            if (component.isEmpty() || component.equals(".") || component.equals("..") || component.indexOf('\0') >= 0)
                throw new FileNotFoundException("Invalid Host document path");
        }
        return path;
    }

    public static void requireMutable(String documentId) throws FileNotFoundException {
        String path = relative(documentId);
        // Reject shared entries before a recursive delete can reach their contents.
        if (path.isEmpty() || path.indexOf('/') < 0)
            throw new FileNotFoundException("Shared storage folders cannot be deleted, renamed or moved");
    }

    public static String name(String name) throws FileNotFoundException {
        if (name == null || name.isEmpty() || name.equals(".") || name.equals("..")
                || name.indexOf('/') >= 0 || name.indexOf('\0') >= 0)
            throw new FileNotFoundException("Invalid file name");
        return name;
    }
}
