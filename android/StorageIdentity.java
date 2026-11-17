package waydroid.manager;

import android.content.Context;
import android.database.Cursor;
import android.provider.DocumentsContract;

public final class StorageIdentity {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Expected Android user");
        Context context = AndroidContext.forUser(Integer.parseInt(args[0]));
        try (Cursor cursor = context.getContentResolver().query(DocumentsContract.buildDocumentUri(
                "waydroid.manager.storage.documents", "__identity"), null, null, null, null)) {
            if (cursor == null || !cursor.moveToFirst()) throw new IllegalStateException("Host storage provider is unavailable");
            System.out.println("STORAGE_UID:" + cursor.getInt(cursor.getColumnIndexOrThrow("uid")));
            System.out.println("STORAGE_PID:" + cursor.getInt(cursor.getColumnIndexOrThrow("pid")));
            System.out.println("STORAGE_PATH:" + cursor.getString(cursor.getColumnIndexOrThrow("path")));
        }
    }
}
