import { describe, expect, it } from "vitest";

import { dynamic as feedDynamic } from "@/app/feed.xml/route";
import { dynamic as jobsSitemapDynamic } from "@/app/jobs/sitemap/[id]/route";
import { dynamic as robotsDynamic } from "@/app/robots";
import { dynamic as sitemapDynamic } from "@/app/sitemap";

describe("public-data metadata route rendering", () => {
	it("keeps mutable-channel consumers request-rendered", () => {
		expect({
			jobsSitemap: jobsSitemapDynamic,
			robots: robotsDynamic,
			sitemap: sitemapDynamic,
			feed: feedDynamic,
		}).toEqual({
			jobsSitemap: "force-dynamic",
			robots: "force-dynamic",
			sitemap: "force-dynamic",
			feed: "force-dynamic",
		});
	});
});
