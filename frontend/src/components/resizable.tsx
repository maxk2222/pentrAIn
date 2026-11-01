import * as React from "react";

/** Drag handle between resizable flex panels. `side` is the screen edge the
 *  panel sits on: a left-side panel grows with +dx, a right-side panel with
 *  −dx. Double-click resets to the default width via onReset. */
export function ResizeHandle({ side, getWidth, onResize, onReset }: {
  side: "left" | "right" | "top";
  getWidth: () => number;
  onResize: (px: number) => void;
  onReset?: () => void;
}) {
  const [dragging, setDragging] = React.useState(false);
  const stopRef = React.useRef<() => void>(() => {});
  const vertical = side === "top";

  React.useEffect(() => () => stopRef.current(), []);

  function startDrag(e: React.MouseEvent) {
    e.preventDefault();
    const start = vertical ? e.clientY : e.clientX;
    const startW = getWidth();
    let frame = 0;
    setDragging(true);
    document.body.style.userSelect = "none";

    const move = (ev: MouseEvent) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const d = (vertical ? ev.clientY : ev.clientX) - start;
        onResize(side === "left" ? startW + d : startW - d);
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
        className={vertical
          ? "h-1.5 shrink-0 cursor-row-resize bg-transparent transition-colors hover:bg-primary/40"
          : "w-1.5 shrink-0 cursor-col-resize bg-transparent transition-colors hover:bg-primary/40"} />
      {/* overlay keeps the drag alive — the noVNC canvas swallows mouse events */}
      {dragging && (
        <div className={vertical
          ? "fixed inset-0 z-50 cursor-row-resize"
          : "fixed inset-0 z-50 cursor-col-resize"} />
      )}
    </>
  );
}
