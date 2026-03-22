import { useRef, useEffect, useCallback } from "react";

export function BackgroundGrid() {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);
  const mouseRef = useRef({ x: -1000, y: -1000 });
  const smoothRef = useRef({ x: -1000, y: -1000 });
  const twinklesRef = useRef<{ col: number; row: number; phase: number; speed: number; delay: number }[]>([]);

  const BUBBLE_R = 320;
  const LERP = 0.04;

  const onMouseMove = useCallback((e: MouseEvent) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    mouseRef.current = {
      x: (e.clientX - rect.left) * dpr,
      y: (e.clientY - rect.top) * dpr,
    };
  }, []);

  const onMouseLeave = useCallback(() => {
    mouseRef.current = { x: -1000, y: -1000 };
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let cw = 0;
    let ch = 0;

    const GRID_SPACING = 60;

    function initTwinkles() {
      const dpr = window.devicePixelRatio || 1;
      const spacing = GRID_SPACING * dpr;
      const cols = Math.ceil(cw / spacing) + 1;
      const rows = Math.ceil(ch / spacing) + 1;

      const allIntersections: { col: number; row: number }[] = [];
      for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
          allIntersections.push({ col: c, row: r });
        }
      }
      const count = Math.max(10, Math.floor(allIntersections.length * 0.4));
      for (let i = allIntersections.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [allIntersections[i], allIntersections[j]] = [allIntersections[j], allIntersections[i]];
      }
      twinklesRef.current = allIntersections.slice(0, count).map((pt) => ({
        col: pt.col,
        row: pt.row,
        phase: Math.random() * Math.PI * 2,
        speed: 0.5 + Math.random() * 1.5,
        delay: Math.random() * 6,
      }));
    }

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      cw = canvas.width;
      ch = canvas.height;
      initTwinkles();
    };
    resize();
    window.addEventListener("resize", resize);
    container.addEventListener("mousemove", onMouseMove);
    container.addEventListener("mouseleave", onMouseLeave);

    function draw(time: number) {
      ctx!.clearRect(0, 0, cw, ch);
      const dpr = window.devicePixelRatio || 1;
      const spacing = GRID_SPACING * dpr;
      const bubbleR = BUBBLE_R * dpr;
      const t = time / 1000;

      smoothRef.current.x += (mouseRef.current.x - smoothRef.current.x) * LERP;
      smoothRef.current.y += (mouseRef.current.y - smoothRef.current.y) * LERP;
      const mx = smoothRef.current.x;
      const my = smoothRef.current.y;

      const cols = Math.ceil(cw / spacing) + 1;
      const rows = Math.ceil(ch / spacing) + 1;

      const offsetX = (cw % spacing) / 2;
      const offsetY = (ch % spacing) / 2;

      const fadeZone = 0;

      // Vertical grid lines
      const segLen = 4 * dpr;
      for (let col = 0; col < cols; col++) {
        const x = offsetX + col * spacing;
        for (let seg = 0; seg < ch; seg += segLen) {
          const yMid = seg + segLen / 2;
          const fadeMul = yMid < fadeZone ? yMid / fadeZone
            : yMid > ch - fadeZone ? (ch - yMid) / fadeZone
            : 1;
          const fade = Math.max(0, fadeMul);
          const dx = x - mx;
          const dy = yMid - my;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const cursorT = Math.max(0, 1 - dist / bubbleR);
          const opacity = (0.06 + cursorT * cursorT * 0.06) * fade;
          ctx!.beginPath();
          ctx!.moveTo(x, seg);
          ctx!.lineTo(x, Math.min(seg + segLen, ch));
          ctx!.strokeStyle = `rgba(60, 73, 173, ${opacity})`;
          ctx!.lineWidth = 1 * dpr;
          ctx!.stroke();
        }
      }

      // Horizontal grid lines
      for (let row = 0; row < rows; row++) {
        const y = offsetY + row * spacing;
        const fadeMul = y < fadeZone ? y / fadeZone
          : y > ch - fadeZone ? (ch - y) / fadeZone
          : 1;
        const fade = Math.max(0, fadeMul);
        for (let seg = 0; seg < cw; seg += segLen) {
          const xMid = seg + segLen / 2;
          const dx = xMid - mx;
          const dy = y - my;
          const dist = Math.sqrt(dx * dx + dy * dy);
          const cursorT = Math.max(0, 1 - dist / bubbleR);
          const opacity = (0.06 + cursorT * cursorT * 0.06) * fade;
          ctx!.beginPath();
          ctx!.moveTo(seg, y);
          ctx!.lineTo(Math.min(seg + segLen, cw), y);
          ctx!.strokeStyle = `rgba(60, 73, 173, ${opacity})`;
          ctx!.lineWidth = 1 * dpr;
          ctx!.stroke();
        }
      }

      // Twinkling dots at intersections
      const dotR = 2 * dpr;
      for (const tw of twinklesRef.current) {
        const x = offsetX + tw.col * spacing;
        const y = offsetY + tw.row * spacing;

        const fadeMul = y < fadeZone ? y / fadeZone
          : y > ch - fadeZone ? (ch - y) / fadeZone
          : 1;

        const raw = Math.sin((t - tw.delay) * tw.speed + tw.phase);
        const opacity = Math.max(0, raw) * 0.35 * Math.max(0, fadeMul);

        if (opacity < 0.01) continue;

        ctx!.beginPath();
        ctx!.arc(x, y, dotR, 0, Math.PI * 2);
        ctx!.fillStyle = `rgba(60, 73, 173, ${opacity})`;
        ctx!.fill();
      }

      animRef.current = requestAnimationFrame(draw);
    }

    animRef.current = requestAnimationFrame(draw);

    return () => {
      cancelAnimationFrame(animRef.current);
      window.removeEventListener("resize", resize);
      container.removeEventListener("mousemove", onMouseMove);
      container.removeEventListener("mouseleave", onMouseLeave);
    };
  }, [onMouseMove, onMouseLeave]);

  return (
    <div ref={containerRef} className="absolute inset-0 pointer-events-none">
      <canvas ref={canvasRef} className="h-full w-full" />
    </div>
  );
}
