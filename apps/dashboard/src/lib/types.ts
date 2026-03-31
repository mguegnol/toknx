export type Stats = {
	nodes_online: number;
	jobs_running: number;
	tokens_total: number;
	tokens_per_second: number;
};

export type ModelRow = {
	hf_id: string;
	estimated_ram_gb: number;
	pricing_tier: string;
	credits_per_1k_tokens: number;
	node_count: number;
};

export type Leader = {
	github_username: string;
	credits_earned: number;
};

export type EventRow = {
	type: string;
	created_at: string;
	node_id?: string;
	models?: string[];
	hardware?: {
		chip?: string;
		ram_gb?: number;
	};
};

