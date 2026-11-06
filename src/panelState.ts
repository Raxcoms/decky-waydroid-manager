export class AppListState {
  visible = 10;
  private overlays = 0;

  leave() {
    if (!this.overlays) this.visible = 10;
  }

  retainForOverlay() {
    this.overlays++;
    let released = false;
    return () => {
      if (!released) this.overlays--;
      released = true;
    };
  }
}
