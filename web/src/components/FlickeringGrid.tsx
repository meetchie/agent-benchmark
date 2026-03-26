import { useRef, useEffect } from "react";

export function FlickeringGrid({
  squareSize = 4,
  gridGap = 6,
  flickerChance = 0.3,
  color = "rgba(180, 190, 230,",
  maxOpacity = 0.28,
}: {
  squareSize?: number;
  gridGap?: number;
  flickerChance?: number;
  color?: string;
  maxOpacity?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let animId: number;
    let cols = 0;
    let rows = 0;
    let squares: Float32Array;
    let dpr = 1;

    function setup() {
      dpr = window.devicePixelRatio || 1;
      const w = container!.clientWidth;
      const h = container!.clientHeight;
      canvas!.width = w * dpr;
      canvas!.height = h * dpr;
      canvas!.style.width = `${w}px`;
      canvas!.style.height = `${h}px`;
      cols = Math.ceil(w / (squareSize + gridGap));
      rows = Math.ceil(h / (squareSize + gridGap));
      squares = new Float32Array(cols * rows);
      for (let i = 0; i < squares.length; i++) {
        squares[i] = Math.random() * maxOpacity;
      }
    }

    setup();

    const isMobile = window.innerWidth < 768;
    let lastTime = -1;
    function animate(time: number) {
      if (lastTime < 0) { lastTime = time; }
      const dt = (time - lastTime) / 1000;

      // Throttle to ~30fps on mobile to save battery
      if (isMobile && dt < 0.033) {
        animId = requestAnimationFrame(animate);
        return;
      }
      lastTime = time;

      for (let i = 0; i < squares.length; i++) {
        if (Math.random() < flickerChance * dt) {
          squares[i] = Math.random() * maxOpacity;
        }
      }

      ctx!.clearRect(0, 0, canvas!.width, canvas!.height);
      const r = (squareSize / 2) * dpr;
      for (let i = 0; i < cols; i++) {
        for (let j = 0; j < rows; j++) {
          const opacity = squares[i * rows + j];
          ctx!.fillStyle = `${color}${opacity})`;
          ctx!.beginPath();
          ctx!.arc(
            i * (squareSize + gridGap) * dpr + r,
            j * (squareSize + gridGap) * dpr + r,
            r,
            0,
            Math.PI * 2,
          );
          ctx!.fill();
        }
      }

      if (!prefersReduced) {
        animId = requestAnimationFrame(animate);
      }
    }

    animId = requestAnimationFrame(animate);

    const ro = new ResizeObserver(() => setup());
    ro.observe(container);

    return () => {
      cancelAnimationFrame(animId);
      ro.disconnect();
    };
  }, [squareSize, gridGap, flickerChance, color, maxOpacity]);

  return (
    <div ref={containerRef} className="absolute inset-0 z-10">
      <canvas ref={canvasRef} className="pointer-events-none" />
    </div>
  );
}
