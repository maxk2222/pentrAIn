import * as React from "react";

/** Drag handle between resizable flex panels. `side` is the screen edge the
 *  panel sits on: a left-side panel grows with +dx, a right-side panel with
 *  −dx. Double-click resets to the default width via onReset. */
export function ResizeHandle({ side, getWidth, onResize, onReset }: {
  side: "left" | "right";
  getWidth: () => number;
  onResize: (px: number) => void;
  onReset?: () => void;
}) {
  const [dragging, setDragging] = React.useState(false);
  const stopRef = React.useRef<() => void>(() => {});

  React.useEffect(() => () => stopRef.current(), []);

  function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    const startX = e.clientX;
    const startW = getWidth();
    let frame = 0;
    setDragging(true);
    document.body.style.userSelect = "none";

    const move = (ev: MouseEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const dx = ev.clientX - startX;
        onResize(side === "left" ? startW + dx : startW - dx);
      });
    };
    const stop = () => {
      cancelAnimationFrame(frame);
      document.body.style.userSelect = "";
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", stop);
      stopRef.current = () => {};
      setDragging(false);
    };
    stopRef.current = stop;
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", stop);
  }

  return (
    <>
      <div onMouseDown={startDrag} onDoubleClick={onReset}
        className="w-1.5 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-primary/40" />
      {/* overlay keeps the drag alive — the noVNC canvas swallows mouse events */}
      {dragging && <div className="fixed inset-0 z-50 cursor-col-resize" />}
    </>
  );
}
