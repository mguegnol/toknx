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
	credits_earned: string;
	credits_earned_subcredits: number;
};

export type EventRow = {
	type: string;
	created_at: string;
	job_id?: string;
	node_id?: string;
	model?: string;
	models?: string[];
	output_tokens?: number;
	error?: string;
	hardware?: {
		chip?: string;
		ram_gb?: number;
	};
};
