package waydroid.manager;

import android.content.Context;
import android.os.Looper;
import android.os.UserHandle;

public final class AndroidContext {
    public static Context forUser(int userId) throws Exception {
        if (Looper.getMainLooper() == null) Looper.prepareMainLooper();
        Class<?> threadClass = Class.forName("android.app.ActivityThread");
        Object thread = threadClass.getMethod("systemMain").invoke(null);
        Context context = (Context) threadClass.getMethod("getSystemContext").invoke(thread);
        Object user = UserHandle.class.getMethod("of", int.class).invoke(null, userId);
        return (Context) Context.class.getMethod("createContextAsUser", UserHandle.class, int.class)
                .invoke(context, user, 0);
    }
}
