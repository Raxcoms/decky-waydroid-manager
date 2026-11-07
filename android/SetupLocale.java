package waydroid.manager;

public final class SetupLocale {
    public static void main(String[] args) throws ReflectiveOperationException {
        if (args.length != 1) {
            throw new IllegalArgumentException("Expected Android language tags");
        }
        Class<?> list = Class.forName("android.os.LocaleList");
        Object locales = list.getMethod("forLanguageTags", String.class).invoke(null, args[0]);
        Class.forName("com.android.internal.app.LocalePicker")
            .getMethod("updateLocales", list).invoke(null, locales);
    }
}
