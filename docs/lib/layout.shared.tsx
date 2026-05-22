import type { BaseLayoutProps } from "fumadocs-ui/layouts/shared";
import Image from "next/image";
import { appName, githubUrl } from "./shared";

export function baseOptions(): BaseLayoutProps {
	return {
		nav: {
			title: (
				<span className="flex items-center gap-2 font-semibold">
					<Image
						src="/brand/openopps-logo.png"
						alt=""
						width={28}
						height={28}
						className="size-7 rounded-md"
						priority
					/>
					<span>{appName}</span>
				</span>
			),
		},
		githubUrl,
	};
}
