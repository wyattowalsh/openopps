import type { ComponentType, SVGProps } from "react";

import type { Entity } from "@/components/openopps-search/search-types";
import { formatCount } from "@/components/openopps-search/search-utils";

export function ExplorerMetric({ label, value }: { label: string; value?: number }) {
	return (
		<div className="opps-metric">
			<div className="font-heading text-xl font-semibold text-primary">
				{formatCount(value)}
			</div>
			<div className="mt-1 truncate font-mono text-[0.68rem] font-semibold tracking-normal text-muted-foreground">
				{label}
			</div>
		</div>
	);
}

export function ExplorerFilterSelect({
	label,
	value,
	onChange,
	options,
	icon: Icon,
}: {
	label: string;
	value: string;
	onChange: (value: string) => void;
	options: Array<{ value: string; label: string }>;
	icon?: ComponentType<SVGProps<SVGSVGElement>>;
}) {
	return (
		<label className="grid gap-1.5 text-sm font-semibold">
			<span className="flex items-center gap-2">
				{Icon ? <Icon className="size-4" /> : null}
				{label}
			</span>
			<select
				value={value}
				onChange={(event) => onChange(event.target.value)}
				className="opps-select"
				aria-label={label}
			>
				{options.map((option) => (
					<option key={`${label}-${option.value}`} value={option.value}>
						{option.label}
					</option>
				))}
			</select>
		</label>
	);
}

export function explorerFacetOptions(values: string[] | undefined) {
	return [
		{ value: "", label: "Any" },
		...(values ?? []).map((value) => ({ value, label: value })),
	];
}

export function explorerEntityLabel(entity: Entity) {
	if (entity === "providers") {
		return "board providers";
	}
	return entity;
}

export function formatExplorerNullableNumber(value: unknown) {
	if (value === null || value === undefined || value === "") {
		return "";
	}
	const numeric = Number(value);
	if (!Number.isFinite(numeric)) {
		return "";
	}
	return formatCount(numeric);
}
