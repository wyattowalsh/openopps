import { renderMermaidSVG } from "beautiful-mermaid";
import { MermaidViewer } from "@/components/mdx/mermaid-viewer";

function normalizeChart(chart: string) {
	return chart.replaceAll("\\n", "\n").trim();
}

export function Mermaid({ chart }: { chart: string }) {
	const normalizedChart = normalizeChart(chart);
	let svg: string | undefined;
	let renderError: string | undefined;

	try {
		svg = renderMermaidSVG(normalizedChart, {
			accent: "var(--primary)",
			bg: "var(--background)",
			border: "var(--border)",
			fg: "var(--foreground)",
			font: "Monaspace Xenon",
			line: "var(--primary)",
			muted: "var(--muted-foreground)",
			padding: 32,
			surface: "var(--card)",
			transparent: true,
		});
	} catch (error) {
		renderError =
			error instanceof Error
				? error.message
				: "Mermaid could not render this diagram.";
	}

	if (svg) {
		return (
			<div
				className="openopps-mermaid"
				role="group"
				aria-label="Mermaid diagram"
			>
				<MermaidViewer svg={svg} />
			</div>
		);
	}

	return (
		<div
			className="openopps-mermaid openopps-mermaid-error"
			role="group"
			aria-label="Mermaid diagram failed to render"
		>
			<p className="openopps-mermaid-title">Mermaid render failed</p>
			<p className="openopps-mermaid-message">{renderError}</p>
			<pre>{normalizedChart}</pre>
		</div>
	);
}
