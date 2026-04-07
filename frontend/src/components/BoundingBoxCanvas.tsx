"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { OCRBlock } from "@/lib/api";

interface Props {
  imageUrl: string;
  blocks: OCRBlock[];
  selectedIndex: number | null;
  onSelect: (index: number) => void;
}

const LABEL_COLOR: Record<string, string> = {
  text:    "#34d399",   // emerald
  title:   "#818cf8",   // indigo
  formula: "#a78bfa",   // violet
  table:   "#38bdf8",   // sky
};

function labelColor(block: OCRBlock) {
  if (block.flagged) return "#fbbf24";            // amber for low confidence
  return LABEL_COLOR[block.label] ?? "#94a3b8";   // slate fallback
}

export default function BoundingBoxCanvas({ imageUrl, blocks, selectedIndex, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef    = useRef<HTMLCanvasElement>(null);
  const imgRef       = useRef<HTMLImageElement | null>(null);
  const [imgLoaded, setImgLoaded] = useState(false);

  // Draw all boxes on the canvas
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const img    = imgRef.current;
    if (!canvas || !img || !imgLoaded) return;

    const ctx  = canvas.getContext("2d")!;
    const W    = canvas.width;
    const H    = canvas.height;

    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(img, 0, 0, W, H);

    // Dark overlay when something is selected
    if (selectedIndex !== null) {
      ctx.fillStyle = "rgba(0,0,0,0.45)";
      ctx.fillRect(0, 0, W, H);
    }

    blocks.forEach((b, i) => {
      if (!b.bbox_2d) return;
      const [x1, y1, x2, y2] = b.bbox_2d;
      const rx = (x1 / 1000) * W;
      const ry = (y1 / 1000) * H;
      const rw = ((x2 - x1) / 1000) * W;
      const rh = ((y2 - y1) / 1000) * H;

      const color   = labelColor(b);
      const isActive = i === selectedIndex;

      // Fill
      ctx.fillStyle = isActive ? `${color}33` : `${color}15`;
      ctx.fillRect(rx, ry, rw, rh);

      // Stroke
      ctx.strokeStyle = color;
      ctx.lineWidth   = isActive ? 2.5 : 1.5;
      ctx.strokeRect(rx, ry, rw, rh);

      // Confidence label
      if (isActive || rw > 60) {
        const conf = `${(b.confidence * 100).toFixed(0)}%`;
        ctx.font         = "bold 11px Inter, system-ui";
        ctx.fillStyle    = color;
        ctx.fillText(conf, rx + 4, ry + 14);
      }
    });
  }, [blocks, selectedIndex, imgLoaded]);

  // Load image once
  useEffect(() => {
    const img  = new Image();
    img.src    = imageUrl;
    img.onload = () => { imgRef.current = img; setImgLoaded(true); };
  }, [imageUrl]);

  // Resize canvas to container, redraw
  useEffect(() => {
    const container = containerRef.current;
    const canvas    = canvasRef.current;
    if (!container || !canvas || !imgLoaded) return;

    const ro = new ResizeObserver(() => {
      canvas.width  = container.clientWidth;
      canvas.height = container.clientHeight;
      draw();
    });
    ro.observe(container);
    canvas.width  = container.clientWidth;
    canvas.height = container.clientHeight;
    draw();
    return () => ro.disconnect();
  }, [imgLoaded, draw]);

  useEffect(() => { draw(); }, [draw]);

  // Click → find which block was hit
  const handleClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const cx   = e.clientX - rect.left;
    const cy   = e.clientY - rect.top;
    const W    = canvas.width;
    const H    = canvas.height;

    for (let i = blocks.length - 1; i >= 0; i--) {
      const b = blocks[i];
      if (!b.bbox_2d) continue;
      const [x1, y1, x2, y2] = b.bbox_2d;
      if (cx >= (x1/1000)*W && cx <= (x2/1000)*W &&
          cy >= (y1/1000)*H && cy <= (y2/1000)*H) {
        onSelect(i);
        return;
      }
    }
  };

  return (
    <div ref={containerRef} className="relative w-full h-full bg-surface-2 rounded-xl overflow-hidden">
      {!imgLoaded && (
        <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-sm">
          Loading image…
        </div>
      )}
      <canvas
        ref={canvasRef}
        onClick={handleClick}
        className="w-full h-full cursor-crosshair"
        style={{ display: imgLoaded ? "block" : "none" }}
      />
      {/* Legend */}
      <div className="absolute bottom-3 left-3 flex items-center gap-3 glass px-3 py-1.5 text-xs">
        {[["text","#34d399"],["formula","#a78bfa"],["table","#38bdf8"],["⚠ low conf","#fbbf24"]].map(([l,c]) => (
          <span key={l} className="flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} />
            <span className="text-slate-400">{l}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
