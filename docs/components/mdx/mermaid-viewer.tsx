import type { ReactNode } from "react";

const viewerScript = String.raw`
(() => {
  if (window.__openoppsMermaidViewerControls) return;
  window.__openoppsMermaidViewerControls = true;

  const maxZoom = 4;
  const minZoom = 0.5;
  const panStep = 88;
  const zoomFactor = 1.18;

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function getParts(root) {
    return {
      canvas: root.querySelector(".openopps-mermaid-canvas"),
      svg: root.querySelector(".openopps-mermaid svg"),
      viewport: root.querySelector(".openopps-mermaid-viewport"),
      zoom: root.querySelector(".openopps-mermaid-zoom"),
      status: root.querySelector(".openopps-mermaid-status"),
    };
  }

  function readState(root) {
    return {
      scale: Number(root.dataset.scale || 1),
      x: Number(root.dataset.offsetX || 0),
      y: Number(root.dataset.offsetY || 0),
    };
  }

  function writeState(root, state) {
    const parts = getParts(root);
    if (!parts.canvas || !parts.zoom) return;

    state.scale = clamp(state.scale, minZoom, maxZoom);
    root.dataset.scale = String(state.scale);
    root.dataset.offsetX = String(state.x);
    root.dataset.offsetY = String(state.y);
    parts.canvas.style.transform = "translate(" + state.x + "px, " + state.y + "px) scale(" + state.scale + ")";
    parts.zoom.textContent = Math.round(state.scale * 100) + "%";
    if (parts.status) {
      parts.status.textContent = "Zoom " + Math.round(state.scale * 100) + "%, pan " + Math.round(state.x) + ", " + Math.round(state.y);
    }
  }

  function getContentBox(root) {
    const parts = getParts(root);
    if (!parts.canvas || !parts.svg) return null;

    const state = readState(root);
    const canvas = parts.canvas.getBoundingClientRect();
    const svg = parts.svg.getBoundingClientRect();
    const scale = state.scale || 1;
    return {
      x: (svg.left - canvas.left) / scale,
      y: (svg.top - canvas.top) / scale,
      width: svg.width / scale,
      height: svg.height / scale,
    };
  }

  function center(root, scale) {
    const parts = getParts(root);
    const box = getContentBox(root);
    if (!parts.viewport || !box) return;

    const nextScale = scale ?? readState(root).scale;
    const viewport = parts.viewport.getBoundingClientRect();
    writeState(root, {
      scale: nextScale,
      x: (viewport.width - box.width * nextScale) / 2 - box.x * nextScale,
      y: (viewport.height - box.height * nextScale) / 2 - box.y * nextScale,
    });
  }

  function fit(root) {
    const parts = getParts(root);
    const box = getContentBox(root);
    if (!parts.viewport || !box) return;

    const viewport = parts.viewport.getBoundingClientRect();
    const scale = Math.min(
      (viewport.width - 48) / box.width,
      (viewport.height - 96) / box.height,
      1
    );
    center(root, clamp(scale, minZoom, maxZoom));
  }

  function zoomAt(root, nextScale, point) {
    const parts = getParts(root);
    if (!parts.viewport) return;

    const current = readState(root);
    nextScale = clamp(nextScale, minZoom, maxZoom);
    const rect = parts.viewport.getBoundingClientRect();
    const origin = point || { x: rect.width / 2, y: rect.height / 2 };
    const contentX = (origin.x - current.x) / current.scale;
    const contentY = (origin.y - current.y) / current.scale;

    writeState(root, {
      scale: nextScale,
      x: origin.x - contentX * nextScale,
      y: origin.y - contentY * nextScale,
    });
  }

  function action(root, name) {
    const state = readState(root);
    switch (name) {
      case "zoom-out":
        root.dataset.viewMode = "manual";
        zoomAt(root, state.scale / zoomFactor);
        break;
      case "zoom-in":
        root.dataset.viewMode = "manual";
        zoomAt(root, state.scale * zoomFactor);
        break;
      case "fit":
      case "reset":
        root.dataset.viewMode = "fit";
        fit(root);
        break;
      case "center":
        root.dataset.viewMode = "manual";
        center(root);
        break;
      case "actual":
        root.dataset.viewMode = "manual";
        center(root, 1.35);
        break;
      case "pan-left":
        root.dataset.viewMode = "manual";
        writeState(root, { ...state, x: state.x - panStep });
        break;
      case "pan-right":
        root.dataset.viewMode = "manual";
        writeState(root, { ...state, x: state.x + panStep });
        break;
      case "pan-up":
        root.dataset.viewMode = "manual";
        writeState(root, { ...state, y: state.y - panStep });
        break;
      case "pan-down":
        root.dataset.viewMode = "manual";
        writeState(root, { ...state, y: state.y + panStep });
        break;
      case "fullscreen":
        if (document.fullscreenElement === root) document.exitFullscreen?.();
        else root.requestFullscreen?.();
        break;
      default:
        return;
    }
  }

  function rootFromEvent(event) {
    return event.target.closest("[data-openopps-mermaid-viewer]");
  }

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-mermaid-action]");
    if (!button) return;

    const root = rootFromEvent(event);
    if (!root) return;
    action(root, button.dataset.mermaidAction);
  });

  document.addEventListener("wheel", (event) => {
    const root = rootFromEvent(event);
    if (!root || !event.target.closest(".openopps-mermaid-viewport")) return;

    event.preventDefault();
    const parts = getParts(root);
    const rect = parts.viewport.getBoundingClientRect();
    const point = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    const state = readState(root);
    root.dataset.viewMode = "manual";
    zoomAt(root, event.deltaY < 0 ? state.scale * zoomFactor : state.scale / zoomFactor, point);
  }, { passive: false });

  document.addEventListener("keydown", (event) => {
    const root = rootFromEvent(event);
    if (!root) return;

    const keyMap = {
      "+": "zoom-in",
      "=": "zoom-in",
      "-": "zoom-out",
      "0": "fit",
      "1": "actual",
      "ArrowLeft": "pan-left",
      "ArrowRight": "pan-right",
      "ArrowUp": "pan-up",
      "ArrowDown": "pan-down",
      "f": "fullscreen",
      "F": "fullscreen",
      "c": "center",
      "C": "center",
      "Escape": "fit",
    };
    const mapped = keyMap[event.key];
    if (!mapped) return;

    event.preventDefault();
    action(root, mapped);
  });

  let drag = null;

  document.addEventListener("pointerdown", (event) => {
    const canvas = event.target.closest(".openopps-mermaid-canvas");
    if (!canvas) return;

    const root = rootFromEvent(event);
    if (!root) return;

    const state = readState(root);
    root.dataset.viewMode = "manual";
    drag = {
      pointerId: event.pointerId,
      root,
      startX: event.clientX,
      startY: event.clientY,
      x: state.x,
      y: state.y,
      scale: state.scale,
    };
    canvas.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  });

  document.addEventListener("pointermove", (event) => {
    if (!drag || drag.pointerId !== event.pointerId) return;

    writeState(drag.root, {
      scale: drag.scale,
      x: drag.x + event.clientX - drag.startX,
      y: drag.y + event.clientY - drag.startY,
    });
  });

  function stopDrag(event) {
    if (drag?.pointerId === event.pointerId) drag = null;
  }

  document.addEventListener("pointerup", stopDrag);
  document.addEventListener("pointercancel", stopDrag);

  function initialize(root) {
    if (root.dataset.viewerReady) return;
    root.dataset.viewerReady = "true";
    root.dataset.viewMode = "fit";
    requestAnimationFrame(() => fit(root));
  }

  function initializeAll() {
    document.querySelectorAll("[data-openopps-mermaid-viewer]").forEach(initialize);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initializeAll, { once: true });
  } else {
    requestAnimationFrame(initializeAll);
  }

  window.addEventListener("resize", () => {
    document.querySelectorAll('[data-openopps-mermaid-viewer][data-view-mode="fit"]').forEach((root) => {
      requestAnimationFrame(() => fit(root));
    });
  });
})();
`;

function ControlButton({
	children,
	label,
	action,
	shortcut,
	className = "",
}: {
	children: ReactNode;
	label: string;
	action: string;
	shortcut?: string;
	className?: string;
}) {
	return (
		<button
			type="button"
			className={`openopps-mermaid-control ${className}`}
			aria-label={label}
			data-mermaid-action={action}
			title={shortcut ? `${label} (${shortcut})` : label}
		>
			{children}
		</button>
	);
}

export function MermaidViewer({ svg }: { svg: string }) {
	return (
		<div
			className="openopps-mermaid-viewer"
			data-openopps-mermaid-viewer
			data-scale="1"
			data-offset-x="0"
			data-offset-y="0"
		>
			<script
				id="openopps-mermaid-viewer-controls"
				dangerouslySetInnerHTML={{ __html: viewerScript }}
			/>
			<div
				className="openopps-mermaid-viewport"
				tabIndex={0}
				role="application"
				aria-label="Interactive Mermaid diagram viewport"
			>
				<div
					className="openopps-mermaid-toolbar"
					aria-label="Mermaid diagram controls"
				>
					<div className="openopps-mermaid-toolbar-copy">
						<span className="openopps-mermaid-eyebrow">Route map</span>
					</div>
					<div className="openopps-mermaid-control-strip">
						<ControlButton
							action="zoom-out"
							label="Zoom out Mermaid diagram"
							shortcut="-"
						>
							-
						</ControlButton>
						<span
							className="openopps-mermaid-zoom"
							aria-live="polite"
							title="Current zoom"
						>
							100%
						</span>
						<ControlButton
							action="zoom-in"
							label="Zoom in Mermaid diagram"
							shortcut="+"
						>
							+
						</ControlButton>
						<ControlButton
							action="fit"
							label="Fit Mermaid diagram"
							shortcut="0"
						>
							Fit
						</ControlButton>
						<ControlButton
							action="actual"
							label="Zoom Mermaid diagram to reading size"
							shortcut="1"
						>
							Read
						</ControlButton>
						<ControlButton
							action="center"
							label="Center Mermaid diagram"
							shortcut="C"
						>
							Mid
						</ControlButton>
						<ControlButton
							action="fullscreen"
							label="Open Mermaid diagram fullscreen"
							shortcut="F"
						>
							Full
						</ControlButton>
					</div>
				</div>
				<div
					className="openopps-mermaid-pan-pad"
					aria-label="Pan Mermaid diagram"
				>
					<ControlButton
						action="pan-left"
						label="Pan Mermaid diagram left"
						shortcut="Left arrow"
						className="openopps-mermaid-pan-left"
					>
						&lt;
					</ControlButton>
					<ControlButton
						action="pan-up"
						label="Pan Mermaid diagram up"
						shortcut="Up arrow"
						className="openopps-mermaid-pan-up"
					>
						^
					</ControlButton>
					<ControlButton
						action="pan-down"
						label="Pan Mermaid diagram down"
						shortcut="Down arrow"
						className="openopps-mermaid-pan-down"
					>
						v
					</ControlButton>
					<ControlButton
						action="pan-right"
						label="Pan Mermaid diagram right"
						shortcut="Right arrow"
						className="openopps-mermaid-pan-right"
					>
						&gt;
					</ControlButton>
				</div>
				<div
					className="openopps-mermaid-canvas"
					dangerouslySetInnerHTML={{ __html: svg }}
				/>
			</div>
			<p className="openopps-mermaid-status" aria-live="polite">
				Zoom 100%, pan 0, 0
			</p>
		</div>
	);
}
