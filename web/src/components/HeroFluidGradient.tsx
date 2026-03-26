import { useRef, useEffect } from "react";

export function HeroFluidGradient() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    let cw = 0;
    let ch = 0;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      cw = canvas.width;
      ch = canvas.height;
    };
    resize();

    const ro = new ResizeObserver(() => resize());
    ro.observe(canvas.parentElement || canvas);

    const blobs = [
      { cx: 0.25, cy: 0.35, r: 0.5, color: [70, 83, 183], speedX: 0.3, speedY: 0.25, phaseX: 0, phaseY: 0.5 },
      { cx: 0.75, cy: 0.65, r: 0.45, color: [107, 120, 209], speedX: 0.2, speedY: 0.35, phaseX: 2, phaseY: 1.2 },
      { cx: 0.5, cy: 0.5, r: 0.55, color: [90, 103, 192], speedX: 0.25, speedY: 0.15, phaseX: 4, phaseY: 3.5 },
    ];

    const isMobile = window.innerWidth < 768;
    let lastDrawTime = -1;
    function draw(time: number) {
      if (lastDrawTime < 0) { lastDrawTime = time; }
      const dt = (time - lastDrawTime) / 1000;

      // Throttle to ~30fps on mobile to save battery
      if (isMobile && dt < 0.033) {
        animRef.current = requestAnimationFrame(draw);
        return;
      }
      lastDrawTime = time;

      const t = time / 1000;
      ctx!.clearRect(0, 0, cw, ch);
      ctx!.globalCompositeOperation = "lighter";

      for (const blob of blobs) {
        const x = (blob.cx + 0.15 * Math.sin(t * blob.speedX + blob.phaseX)) * cw;
        const y = (blob.cy + 0.1 * Math.cos(t * blob.speedY + blob.phaseY)) * ch;
        const r = blob.r * Math.max(cw, ch);

        const grad = ctx!.createRadialGradient(x, y, 0, x, y, r);
        grad.addColorStop(0, `rgba(${blob.color[0]}, ${blob.color[1]}, ${blob.color[2]}, 0.12)`);
        grad.addColorStop(0.5, `rgba(${blob.color[0]}, ${blob.color[1]}, ${blob.color[2]}, 0.04)`);
        grad.addColorStop(1, "transparent");

        ctx!.fillStyle = grad;
        ctx!.fillRect(0, 0, cw, ch);
      }

      ctx!.globalCompositeOperation = "source-over";

      if (!prefersReduced) {
        animRef.current = requestAnimationFrame(draw);
      }
    }

    animRef.current = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(animRef.current);
      ro.disconnect();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 h-full w-full pointer-events-none z-0"
    />
  );
}
