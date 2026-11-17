package waydroid.manager;

import android.content.Context;
import android.content.pm.ProviderInfo;

public final class StorageIdentity {
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Expected Android user");
        Context context = AndroidContext.forUser(Integer.parseInt(args[0]));
        ProviderInfo provider = context.getPackageManager().resolveContentProvider("media", 0);
        if (provider == null) throw new IllegalStateException("Android media provider is unavailable");
        System.out.println("STORAGE_UID:" + provider.applicationInfo.uid);
    }
}
