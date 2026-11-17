package waydroid.manager.storage;

import android.database.Cursor;
import android.database.MatrixCursor;
import android.os.Binder;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.os.Process;
import android.net.Uri;
import android.provider.DocumentsContract;
import android.provider.DocumentsContract.Document;
import android.provider.DocumentsContract.Root;
import android.provider.DocumentsProvider;
import android.webkit.MimeTypeMap;
import java.io.File;
import java.io.FileNotFoundException;
import java.io.IOException;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.Comparator;
import java.util.Locale;

public final class HostDocumentsProvider extends DocumentsProvider {
    private static final String AUTHORITY = "waydroid.manager.storage.documents";
    private static final String[] COLUMNS = {Document.COLUMN_DOCUMENT_ID, Document.COLUMN_DISPLAY_NAME,
        Document.COLUMN_MIME_TYPE, Document.COLUMN_FLAGS, Document.COLUMN_SIZE, Document.COLUMN_LAST_MODIFIED};

    @Override
    public boolean onCreate() { return true; }

    private File host() { return new File(getContext().getFilesDir(), "Host"); }

    private File file(String id) throws FileNotFoundException {
        String relative = SharePolicy.relative(id);
        File result = relative.isEmpty() ? host() : new File(host(), relative);
        try {
            if (!relative.isEmpty()) {
                File share = new File(host(), relative.split("/", 2)[0]);
                String base = share.getCanonicalPath();
                String actual = result.getCanonicalPath();
                if (!actual.equals(base) && !actual.startsWith(base + "/"))
                    throw new FileNotFoundException("The file is outside its shared folder");
            }
        } catch (IOException error) {
            throw failure(error);
        }
        if (!result.exists()) throw new FileNotFoundException("The shared file is unavailable");
        return result;
    }

    private static FileNotFoundException failure(Exception error) {
        FileNotFoundException result = new FileNotFoundException(error.getMessage());
        result.initCause(error);
        return result;
    }

    private static void add(MatrixCursor cursor, MatrixCursor.RowBuilder row, String name, Object value) {
        if (cursor.getColumnIndex(name) >= 0) row.add(name, value);
    }

    private void include(MatrixCursor cursor, String id, File file) {
        MatrixCursor.RowBuilder row = cursor.newRow();
        boolean directory = file.isDirectory();
        String mime = Document.MIME_TYPE_DIR;
        if (!directory) {
            String name = file.getName();
            int extension = name.lastIndexOf('.');
            mime = extension < 0 ? null : MimeTypeMap.getSingleton()
                .getMimeTypeFromExtension(name.substring(extension + 1).toLowerCase(Locale.ROOT));
            if (mime == null) mime = "application/octet-stream";
        }
        int flags = directory && file.canWrite() && !SharePolicy.ROOT.equals(id) ? Document.FLAG_DIR_SUPPORTS_CREATE : 0;
        if (!directory && file.canWrite()) flags |= Document.FLAG_SUPPORTS_WRITE;
        try {
            SharePolicy.requireMutable(id);
            if (file.getParentFile().canWrite()) flags |= Document.FLAG_SUPPORTS_DELETE | Document.FLAG_SUPPORTS_RENAME;
        } catch (FileNotFoundException protectedFolder) { }
        add(cursor, row, Document.COLUMN_DOCUMENT_ID, id);
        add(cursor, row, Document.COLUMN_DISPLAY_NAME, SharePolicy.ROOT.equals(id) ? "Host" : file.getName());
        add(cursor, row, Document.COLUMN_MIME_TYPE, mime);
        add(cursor, row, Document.COLUMN_FLAGS, flags);
        add(cursor, row, Document.COLUMN_SIZE, directory ? null : file.length());
        add(cursor, row, Document.COLUMN_LAST_MODIFIED, file.lastModified());
    }

    @Override
    public Cursor queryRoots(String[] projection) {
        MatrixCursor cursor = new MatrixCursor(projection != null ? projection : new String[] {
            Root.COLUMN_ROOT_ID, Root.COLUMN_DOCUMENT_ID, Root.COLUMN_TITLE, Root.COLUMN_FLAGS,
            Root.COLUMN_ICON, Root.COLUMN_AVAILABLE_BYTES, Root.COLUMN_MIME_TYPES});
        if (!new File(host(), "Home").isDirectory()) return cursor;
        MatrixCursor.RowBuilder row = cursor.newRow();
        add(cursor, row, Root.COLUMN_ROOT_ID, SharePolicy.ROOT);
        add(cursor, row, Root.COLUMN_DOCUMENT_ID, SharePolicy.ROOT);
        add(cursor, row, Root.COLUMN_TITLE, "Host");
        add(cursor, row, Root.COLUMN_FLAGS, Root.FLAG_LOCAL_ONLY | Root.FLAG_SUPPORTS_IS_CHILD);
        add(cursor, row, Root.COLUMN_ICON, android.R.drawable.ic_menu_save);
        add(cursor, row, Root.COLUMN_AVAILABLE_BYTES, new File(host(), "Home").getUsableSpace());
        add(cursor, row, Root.COLUMN_MIME_TYPES, "*/*");
        return cursor;
    }

    @Override
    public Cursor queryDocument(String id, String[] projection) throws FileNotFoundException {
        if (id.equals("__identity")) {
            if (Binder.getCallingUid() != 0) throw new SecurityException("Only the host can prepare storage");
            MatrixCursor cursor = new MatrixCursor(new String[] {"uid", "pid", "path"});
            try { cursor.addRow(new Object[] {Process.myUid(), Process.myPid(), host().getCanonicalPath()}); }
            catch (IOException error) { throw failure(error); }
            return cursor;
        }
        if (id.equals("__refresh")) {
            if (Binder.getCallingUid() != 0) throw new SecurityException("Only the host can refresh storage");
            changed();
            id = SharePolicy.ROOT;
        }
        MatrixCursor cursor = new MatrixCursor(projection != null ? projection : COLUMNS);
        include(cursor, id, file(id));
        return cursor;
    }

    @Override
    public Cursor queryChildDocuments(String parent, String[] projection, String sortOrder) throws FileNotFoundException {
        File directory = file(parent);
        File[] children = directory.listFiles();
        if (children == null) throw new FileNotFoundException("The shared folder cannot be read");
        Arrays.sort(children, Comparator.comparing(File::getName, String.CASE_INSENSITIVE_ORDER));
        MatrixCursor cursor = new MatrixCursor(projection != null ? projection : COLUMNS);
        for (File child : children) {
            String id = parent + "/" + child.getName();
            try {
                File resolved = file(id);
                if (resolved.isDirectory() || resolved.isFile()) include(cursor, id, resolved);
            } catch (FileNotFoundException unavailable) { }
        }
        cursor.setNotificationUri(getContext().getContentResolver(), DocumentsContract.buildChildDocumentsUri(AUTHORITY, parent));
        return cursor;
    }

    @Override
    public ParcelFileDescriptor openDocument(String id, String mode, CancellationSignal signal) throws FileNotFoundException {
        File target = file(id);
        if (!target.isFile()) throw new FileNotFoundException("Only regular files can be opened");
        int access = ParcelFileDescriptor.parseMode(mode);
        if (mode.equals("r")) return ParcelFileDescriptor.open(target, access);
        try {
            return ParcelFileDescriptor.open(target, access, new Handler(Looper.getMainLooper()), error -> changed());
        } catch (IOException error) { throw failure(error); }
    }

    @Override
    public String createDocument(String parent, String mime, String displayName) throws FileNotFoundException {
        if (SharePolicy.ROOT.equals(parent)) throw new FileNotFoundException("Only the host can add shared folders");
        File directory = file(parent);
        String name = SharePolicy.name(displayName);
        for (int number = 0; ; number++) {
            File target = new File(directory, number == 0 ? name : name + " (" + number + ")");
            try {
                if (Document.MIME_TYPE_DIR.equals(mime)) Files.createDirectory(target.toPath());
                else Files.createFile(target.toPath());
                changed();
                return parent + "/" + target.getName();
            } catch (FileAlreadyExistsException duplicate) {
                continue;
            } catch (IOException error) { throw failure(error); }
        }
    }

    private void delete(File target) throws IOException {
        if (!Files.isSymbolicLink(target.toPath()) && target.isDirectory()) {
            File[] children = target.listFiles();
            if (children == null) throw new IOException("The shared folder cannot be read");
            for (File child : children) delete(child);
        }
        Files.delete(target.toPath());
    }

    @Override
    public void deleteDocument(String id) throws FileNotFoundException {
        SharePolicy.requireMutable(id);
        try { delete(file(id)); changed(); }
        catch (IOException error) { throw failure(error); }
    }

    @Override
    public String renameDocument(String id, String displayName) throws FileNotFoundException {
        SharePolicy.requireMutable(id);
        File source = file(id);
        File target = new File(source.getParentFile(), SharePolicy.name(displayName));
        try { Files.move(source.toPath(), target.toPath()); }
        catch (IOException error) { throw failure(error); }
        changed();
        return id.substring(0, id.lastIndexOf('/') + 1) + target.getName();
    }

    @Override
    public boolean isChildDocument(String parent, String child) {
        try { return file(child).getCanonicalPath().startsWith(file(parent).getCanonicalPath() + "/"); }
        catch (IOException error) { return false; }
    }

    private void changed() {
        getContext().getContentResolver().notifyChange(DocumentsContract.buildRootsUri(AUTHORITY), null);
        getContext().getContentResolver().notifyChange(Uri.parse("content://" + AUTHORITY), null);
    }
}
