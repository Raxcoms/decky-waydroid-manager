package waydroid.manager.probe;

import android.app.Activity;
import android.app.Presentation;
import android.hardware.display.DisplayManager;
import android.os.Bundle;
import android.util.Log;
import android.view.Display;
import android.view.Gravity;
import android.widget.TextView;

public final class ProbeActivity extends Activity implements DisplayManager.DisplayListener {
    private DisplayManager displays;
    private Presentation presentation;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        TextView primary = new TextView(this);
        primary.setText("Waydroid primary display\nThe external display should show a blue test screen.");
        primary.setTextSize(24);
        primary.setTextColor(0xffffffff);
        primary.setBackgroundColor(0xff243629);
        primary.setGravity(Gravity.CENTER);
        setContentView(primary);
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
        TextView content = new TextView(presentation.getContext());
        content.setText("Waydroid external display\nDisplay " + external[0].getDisplayId());
        content.setTextSize(24);
        content.setTextColor(0xffffffff);
        content.setBackgroundColor(0xff164e91);
        content.setGravity(Gravity.CENTER);
        presentation.setContentView(content);
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
