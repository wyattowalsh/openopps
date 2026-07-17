import {
	BriefcaseBusiness,
	Building2,
	Database,
	Route,
} from "lucide-react";
import type { ComponentType, SVGProps } from "react";

import type { Entity, SearchChunk, SearchManifest } from "@/components/openopps-search/search-types";
import { formatCount } from "@/components/openopps-search/search-utils";

import { explorerEntityLabel } from "./explorer-shared";

const ENTITY_OPTIONS: Array<{
	value: Entity;
	label: string;
	icon: ComponentType<SVGProps<SVGSVGElement>>;
}> = [
	{ value: "jobs", label: "Jobs", icon: BriefcaseBusiness },
	{ value: "boards", label: "Boards", icon: Building2 },
	{ value: "providers", label: "Board providers", icon: Route },
];

type ExplorerEntityTabsProps = {
	entity: Entity;
	manifest: SearchManifest | null;
	activeChunk: SearchChunk | undefined;
	onSelect: (entity: Entity) => void;
};

export function ExplorerEntityTabs({
	entity,
	manifest,
	activeChunk,
	onSelect,
}: ExplorerEntityTabsProps) {
	return (
		<div className="mt-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
			<div className="grid gap-2 sm:grid-cols-3">
				{ENTITY_OPTIONS.map((option) => {
					const Icon = option.icon;
					const active = option.value === entity;
					return (
						<button
							key={option.value}
							type="button"
							onClick={() => onSelect(option.value)}
							className="opps-entity-tab"
							aria-pressed={active}
							data-active={active ? "true" : "false"}
							aria-label={`Show ${option.label}`}
						>
							<Icon className="size-4 shrink-0" />
							<span className="min-w-0 truncate">{option.label}</span>
							<span className="ml-auto font-mono text-xs opacity-75">
								{formatCount(manifest?.entities[option.value].count)}
							</span>
						</button>
					);
				})}
			</div>
			<div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
				<Database className="size-4" />
				<span>
					{formatCount(activeChunk?.count ?? manifest?.entities[entity].count)}{" "}
					indexed {explorerEntityLabel(entity)}
				</span>
			</div>
		</div>
	);
}
