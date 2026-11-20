package waydroid.manager;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;

public final class InputGuard {
    private static Object manager;
    private static Method dispatch;
    private static volatile boolean changed;

    private static void output(String message) throws Exception {
        new FileOutputStream(FileDescriptor.out)
            .write((message + "\n").getBytes(StandardCharsets.UTF_8));
    }

    private static synchronized void restore() throws Exception {
        if (changed) {
            dispatch.invoke(manager, true);
            changed = false;
        }
    }

    public static void main(String[] args) {
        try {
            Class<?> binder = Class.forName("android.os.IBinder");
            Object service = Class.forName("android.os.ServiceManager")
                .getMethod("getService", String.class).invoke(null, "window");
            manager = Class.forName("android.view.IWindowManager$Stub")
                .getMethod("asInterface", binder).invoke(null, service);
            dispatch = Class.forName("android.view.IWindowManager")
                .getMethod("setEventDispatching", boolean.class);
            Runtime.getRuntime().addShutdownHook(new Thread(() -> {
                try {
                    restore();
                } catch (Exception error) {
                    System.err.println("Could not restore Android input: " + error);
                }
            }));
            try {
                changed = true;
                dispatch.invoke(manager, false);
                output("INPUT_GUARDED");
                // The plugin owns this pipe. EOF also restores input if the plugin exits.
                while (System.in.read() != -1) { }
            } finally {
                restore();
            }
            output("INPUT_RESTORED");
        } catch (Exception error) {
            System.err.println("Android input guard failed: " + error);
            System.exit(1);
        }
    }
}
