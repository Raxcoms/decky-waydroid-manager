package waydroid.manager;

import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.content.res.Resources;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.drawable.BitmapDrawable;
import android.graphics.drawable.Drawable;
import android.os.Looper;
import android.os.UserHandle;
import android.util.Base64;
import android.util.DisplayMetrics;
import java.io.ByteArrayOutputStream;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

public final class ExportIcon {
    public static void main(String[] args) throws Exception {
        if (args.length != 2) throw new IllegalArgumentException("Expected package and Android user");
        if (Looper.getMainLooper() == null) Looper.prepareMainLooper();
        Class<?> threadClass = Class.forName("android.app.ActivityThread");
        Object thread = threadClass.getMethod("systemMain").invoke(null);
        Context context = (Context) threadClass.getMethod("getSystemContext").invoke(thread);
        Object user = UserHandle.class.getMethod("of", int.class).invoke(null, Integer.parseInt(args[1]));
        context = (Context) Context.class.getMethod("createContextAsUser", UserHandle.class, int.class)
                .invoke(context, user, 0);
        PackageManager packages = context.getPackageManager();
        Intent launch = packages.getLaunchIntentForPackage(args[0]);
        if (launch == null) throw new IllegalArgumentException("The app has no launcher activity");
        ResolveInfo resolved = packages.resolveActivity(launch, 0);
        if (resolved == null || !args[0].equals(resolved.activityInfo.packageName))
            throw new IllegalArgumentException("The launcher activity changed");
        Drawable icon;
        try {
            String owner = resolved.resolvePackageName != null ? resolved.resolvePackageName : args[0];
            Resources resources = packages.getResourcesForApplication(owner);
            icon = resources.getDrawableForDensity(resolved.getIconResource(), DisplayMetrics.DENSITY_XXXHIGH, null);
        } catch (Resources.NotFoundException error) {
            icon = resolved.loadIcon(packages);
        }
        if (icon instanceof BitmapDrawable) ((BitmapDrawable) icon).setFilterBitmap(true);
        Bitmap bitmap = Bitmap.createBitmap(512, 512, Bitmap.Config.ARGB_8888);
        icon.setBounds(0, 0, bitmap.getWidth(), bitmap.getHeight());
        icon.draw(new Canvas(bitmap));
        ByteArrayOutputStream png = new ByteArrayOutputStream();
        bitmap.compress(Bitmap.CompressFormat.PNG, 100, png);
        String result = "ICON_PNG:" + Base64.encodeToString(png.toByteArray(), Base64.NO_WRAP) + "\n";
        new FileOutputStream(FileDescriptor.out).write(result.getBytes(StandardCharsets.UTF_8));
        bitmap.recycle();
    }
}
