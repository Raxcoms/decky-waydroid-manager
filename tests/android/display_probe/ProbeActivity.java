package waydroid.manager.probe;

import android.app.Activity;
import android.app.Presentation;
import android.content.Context;
import android.hardware.display.DisplayManager;
import android.os.Bundle;
import android.util.Log;
import android.view.Display;
import android.view.Gravity;
import android.widget.TextView;

public final class ProbeActivity extends Activity implements DisplayManager.DisplayListener {
    private DisplayManager displays;
    private Presentation presentation;

    private TextView animatedLabel(Context context, String label, int color) {
        TextView view = new TextView(context);
        view.setTextSize(24);
        view.setTextColor(0xffffffff);
        view.setBackgroundColor(color);
        view.setGravity(Gravity.CENTER);
        view.post(new Runnable() {
            private long frame;
            public void run() {
                if (!view.isAttachedToWindow()) return;
                view.setText(label + "\nFrame " + frame++);
                view.postOnAnimation(this);
            }
        });
        return view;
    }

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        setContentView(animatedLabel(this, "Waydroid primary display", 0xff243629));
        displays = (DisplayManager) getSystemService(DISPLAY_SERVICE);
        displays.registerDisplayListener(this, null);
        updatePresentation();
    }

    private void updatePresentation() {
        Display[] external = displays.getDisplays(DisplayManager.DISPLAY_CATEGORY_PRESENTATION);
        Log.i("WaydroidManagerProbe", "presentationDisplays=" + external.length);
        if (presentation != null) {
            presentation.dismiss();
            presentation = null;
        }
        if (external.length == 0) return;
        presentation = new Presentation(this, external[0]);
        presentation.setContentView(animatedLabel(presentation.getContext(),
                "Waydroid external display " + external[0].getDisplayId(), 0xff164e91));
        presentation.show();
    }

    @Override
    public void onDisplayAdded(int id) { updatePresentation(); }

    @Override
    public void onDisplayRemoved(int id) { updatePresentation(); }

    @Override
    public void onDisplayChanged(int id) { }

    @Override
    public void onDestroy() {
        displays.unregisterDisplayListener(this);
        if (presentation != null) presentation.dismiss();
        super.onDestroy();
    }
}
