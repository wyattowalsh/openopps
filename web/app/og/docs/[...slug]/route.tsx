/* eslint-disable @next/next/no-img-element */

import { getDocsOgPage, getDocsOgPages } from "@/lib/docs-og-data";
import { notFound } from "next/navigation";
import { ImageResponse } from "next/og";
import { appName } from "@/lib/shared";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { docsOgPageSlug } from "./route-utils";

export const revalidate = false;
export const runtime = "nodejs";

const palette = {
	paper: "#f7f1df",
	card: "#fff9ea",
	pine: "#2f6f50",
	ink: "#1d281f",
	brass: "#d99629",
	border: "#cfc1a6",
};

const fontFamily = '"Monaspace Neon", "Monaspace Argon", ui-monospace, monospace';

const logo = readFile(
	path.join(process.cwd(), "public", "brand", "openopps-logo.png"),
).then((buffer) => `data:image/png;base64,${buffer.toString("base64")}`);

export async function GET(
	_req: Request,
	{ params }: RouteContext<"/og/docs/[...slug]">,
) {
	const { slug } = await params;
	const pageSlug = docsOgPageSlug(slug);
	if (!pageSlug) notFound();
	const page = getDocsOgPage(pageSlug);
	if (!page) notFound();
	const logoSrc = await logo;
	const description =
		page.description ??
		"Public hiring board docs, provider checks, storage, and export workflows for OpenOpps.";

	return new ImageResponse(
		<div
			style={{
				position: "relative",
				display: "flex",
				width: "100%",
				height: "100%",
				overflow: "hidden",
				background: palette.paper,
				color: palette.ink,
				fontFamily,
			}}
		>
			<svg
				width="1200"
				height="630"
				viewBox="0 0 1200 630"
				style={{ position: "absolute", inset: 0 }}
			>
				<rect width="1200" height="630" fill={palette.paper} />
				{Array.from({ length: 24 }).map((_, index) => (
					<line
						key={`v-${index}`}
						x1={index * 54}
						y1="0"
						x2={index * 54}
						y2="630"
						stroke={palette.border}
						strokeWidth="1"
						opacity="0.42"
					/>
				))}
				{Array.from({ length: 14 }).map((_, index) => (
					<line
						key={`h-${index}`}
						x1="0"
						y1={index * 48}
						x2="1200"
						y2={index * 48}
						stroke={palette.border}
						strokeWidth="1"
						opacity="0.42"
					/>
				))}
				<circle
					cx="1006"
					cy="315"
					r="220"
					fill={palette.card}
					stroke={palette.border}
					strokeWidth="3"
				/>
				<circle
					cx="1006"
					cy="315"
					r="168"
					fill="none"
					stroke={palette.border}
					strokeWidth="2"
					opacity="0.65"
				/>
				<rect
					x="790"
					y="112"
					width="410"
					height="406"
					rx="34"
					fill="rgba(255,249,234,0.72)"
					stroke={palette.border}
					strokeWidth="2"
				/>
				<rect
					x="840"
					y="446"
					width="260"
					height="52"
					rx="16"
					fill={palette.ink}
					opacity="0.94"
				/>
				<path
					d="M872 472H1026"
					stroke={palette.paper}
					strokeWidth="4"
					opacity="0.72"
				/>
				<circle cx="1062" cy="472" r="10" fill={palette.brass} />
				<rect
					x="24"
					y="24"
					width="1152"
					height="582"
					fill="none"
					stroke={palette.border}
					strokeWidth="3"
				/>
			</svg>

			<img
				src={logoSrc}
				width={300}
				height={300}
				alt=""
				style={{ position: "absolute", right: 144, top: 158 }}
			/>

			<div
				style={{
					position: "absolute",
					left: 72,
					top: 72,
					display: "flex",
					width: 650,
					height: 486,
					flexDirection: "column",
					justifyContent: "space-between",
					border: `2px solid ${palette.border}`,
					borderRadius: 30,
					background: "rgba(255, 249, 234, 0.94)",
					padding: "48px 52px",
				}}
			>
				<div style={{ display: "flex", alignItems: "center", gap: 18 }}>
					<div
						style={{
							display: "flex",
							width: 86,
							height: 86,
							alignItems: "center",
							justifyContent: "center",
							border: `2px solid ${palette.border}`,
							borderRadius: 20,
							background: palette.paper,
						}}
					>
						<img src={logoSrc} width={76} height={76} alt="" />
					</div>
					<div style={{ display: "flex", flexDirection: "column" }}>
						<div
							style={{
								color: palette.pine,
								fontFamily,
								fontSize: 26,
								letterSpacing: 2,
							}}
						>
							{`${appName.toUpperCase()} DOCS`}
						</div>
						<div
							style={{
								color: palette.ink,
								fontFamily,
								fontSize: 20,
							}}
						>
							Open door to public opportunities
						</div>
					</div>
				</div>

				<div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
					<div
						style={{
							fontFamily,
							fontSize: 72,
							fontWeight: 700,
							letterSpacing: 0,
							lineHeight: 0.96,
						}}
					>
						{page.title}
					</div>
					<div
						style={{
							maxWidth: 540,
							color: palette.ink,
							fontFamily,
							fontSize: 30,
							lineHeight: 1.25,
						}}
					>
						{description}
					</div>
				</div>

				<div
					style={{
						display: "flex",
						alignItems: "center",
						justifyContent: "space-between",
						borderTop: `2px solid ${palette.border}`,
						paddingTop: 20,
						color: palette.pine,
						fontFamily,
						fontSize: 22,
					}}
				>
					<span>openopps.dev/docs</span>
					<span>CLI docs for public hiring boards</span>
				</div>
			</div>
		</div>,
		{
			width: 1200,
			height: 630,
		},
	);
}

export function generateStaticParams() {
	return getDocsOgPages().map((page) => ({
		slug: [...page.slug, "image.png"],
	}));
}
