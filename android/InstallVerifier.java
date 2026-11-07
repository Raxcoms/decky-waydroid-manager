package waydroid.manager;

import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;

public final class InstallVerifier {
    private static void output(String message, boolean error) throws Exception {
        new FileOutputStream(error ? FileDescriptor.err : FileDescriptor.out)
            .write((message + "\n").getBytes(StandardCharsets.UTF_8));
    }

    public static void main(String[] args) {
        try {
            Class<?> api = Class.forName("android.content.pm.IPackageManager");
            Method verify = api.getMethod("verifyPendingInstall", int.class, int.class);
            if (args.length != 0 && args.length != 2) {
                throw new IllegalArgumentException("Expected verification ID and result");
            }
            Class<?> binder = Class.forName("android.os.IBinder");
            Object service = Class.forName("android.os.ServiceManager")
                .getMethod("getService", String.class).invoke(null, "package");
            Object manager = Class.forName("android.content.pm.IPackageManager$Stub")
                .getMethod("asInterface", binder).invoke(null, service);
            if (args.length == 0) {
                output("VERIFIER_API_AVAILABLE", false);
                return;
            }
            int id = Integer.parseInt(args[0]);
            int result = Integer.parseInt(args[1]);
            if (id < 0 || (result != -1 && result != 2)) {
                throw new IllegalArgumentException("Invalid verification result");
            }
            verify.invoke(manager, id, result);
            output("VERIFICATION_SENT", false);
        } catch (Exception error) {
            Throwable cause = error instanceof InvocationTargetException ? error.getCause() : error;
            try {
                output("Verification API failed: " + cause, true);
            } catch (Exception ignored) {
                System.exit(1);
            }
            System.exit(1);
        }
    }
}
