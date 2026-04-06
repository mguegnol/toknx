import type { EventRow, Leader, ModelRow, Stats } from '$lib/types';

const MOCK_MODELS: ModelRow[] = [
	{
		hf_id: 'mlx-community/Llama-3.2-1B-Instruct-4bit',
		estimated_ram_gb: 2.4,
		pricing_tier: 'S',
		credits_per_1k_tokens: 1,
		node_count: 6
	},
	{
		hf_id: 'mlx-community/Qwen2.5-3B-Instruct-4bit',
		estimated_ram_gb: 5.8,
		pricing_tier: 'S',
		credits_per_1k_tokens: 1,
		node_count: 4
	},
	{
		hf_id: 'mlx-community/Qwen2.5-Coder-7B-Instruct-4bit',
		estimated_ram_gb: 13.6,
		pricing_tier: 'M',
		credits_per_1k_tokens: 2,
		node_count: 3
	},
	{
		hf_id: 'mlx-community/Meta-Llama-3.1-8B-Instruct-4bit',
		estimated_ram_gb: 15.2,
		pricing_tier: 'M',
		credits_per_1k_tokens: 2,
		node_count: 2
	}
];

const MOCK_LEADERS: Leader[] = [
	{
		github_username: 'solinox',
		credits_earned: '438.12',
		credits_earned_subcredits: 438_120
	},
	{
		github_username: 'cynotw',
		credits_earned: '321.87',
		credits_earned_subcredits: 321_870
	},
	{
		github_username: 'zongrux',
		credits_earned: '244.51',
		credits_earned_subcredits: 244_510
	},
	{
		github_username: 'stefanz',
		credits_earned: '198.34',
		credits_earned_subcredits: 198_340
	},
	{
		github_username: 'kariam9k',
		credits_earned: '155.09',
		credits_earned_subcredits: 155_090
	}
];

const NODE_HARDWARE = [
	{ chip: 'M4 Max', ram_gb: 128 },
	{ chip: 'M3 Pro', ram_gb: 36 },
	{ chip: 'M2 Max', ram_gb: 64 },
	{ chip: 'M1 Ultra', ram_gb: 128 }
];

const JOB_PHASES = ['queued', 'warming cache', 'dispatching', 'streaming first tokens'];

type MockSnapshot = {
	stats: Stats;
	models: ModelRow[];
	leaders: Leader[];
	events: EventRow[];
};

const MOCK_TOKENS_BASE = 248_321;
const MOCK_TOKENS_EPOCH_MS = Date.UTC(2026, 3, 1, 0, 0, 0);
const MOCK_TOKENS_PER_SECOND = 21;

function isoOffset(secondsAgo: number) {
	return new Date(Date.now() - secondsAgo * 1000).toISOString();
}

function formatSubcredits(value: number) {
	return (value / 1000).toFixed(2);
}

function currentMockTokensTotal(now = Date.now()) {
	const elapsedSeconds = Math.max(0, Math.floor((now - MOCK_TOKENS_EPOCH_MS) / 1000));
	return MOCK_TOKENS_BASE + elapsedSeconds * MOCK_TOKENS_PER_SECOND;
}

function createEvent(sequence: number): EventRow {
	const model = MOCK_MODELS[sequence % MOCK_MODELS.length];
	const hardware = NODE_HARDWARE[sequence % NODE_HARDWARE.length];
	const nodeId = `demo-node-${(sequence % 8) + 1}`;
	const eventType = sequence % 10;

	if (eventType === 0) {
		return {
			type: 'node_online',
			created_at: new Date().toISOString(),
			node_id: nodeId,
			models: [model.hf_id],
			hardware
		};
	}
	if (eventType === 1 || eventType === 2 || eventType === 3 || eventType === 4) {
		return {
			type: 'job_started',
			created_at: new Date().toISOString(),
			job_id: `demo-job-${sequence}`,
			node_id: nodeId,
			model: `${model.hf_id} • ${JOB_PHASES[sequence % JOB_PHASES.length]}`
		};
	}
	if (eventType === 5 || eventType === 6 || eventType === 7 || eventType === 8) {
		return {
			type: 'job_completed',
			created_at: new Date().toISOString(),
			job_id: `demo-job-${sequence}`,
			node_id: nodeId,
			model: model.hf_id,
			output_tokens: 144 + ((sequence * 17) % 240)
		};
	}
	if (eventType === 9) {
		return {
			type: 'node_offline',
			created_at: new Date().toISOString(),
			node_id: nodeId,
			models: [model.hf_id],
			hardware
		};
	}
	return {
		type: 'job_completed',
		created_at: new Date().toISOString(),
		job_id: `demo-job-${sequence}`,
		node_id: nodeId,
		model: model.hf_id,
		output_tokens: 160
	};
}

export function getMockDashboardSnapshot(): MockSnapshot {
	return {
		stats: {
			nodes_online: 11,
			jobs_running: 6,
			tokens_total: currentMockTokensTotal(),
			tokens_per_second: 184.6
		},
		models: MOCK_MODELS.map((model) => ({ ...model })),
		leaders: MOCK_LEADERS.map((leader) => ({ ...leader })),
		events: [
			{
				type: 'job_completed',
				created_at: isoOffset(12),
				job_id: 'demo-job-8021',
				node_id: 'demo-node-3',
				model: MOCK_MODELS[2].hf_id,
				output_tokens: 91
			},
			{
				type: 'job_started',
				created_at: isoOffset(28),
				job_id: 'demo-job-8020',
				node_id: 'demo-node-1',
				model: `${MOCK_MODELS[0].hf_id} • streaming first tokens`
			},
			{
				type: 'job_completed',
				created_at: isoOffset(46),
				node_id: 'demo-node-7',
				job_id: 'demo-job-8018',
				model: MOCK_MODELS[1].hf_id,
				output_tokens: 184
			},
			{
				type: 'job_completed',
				created_at: isoOffset(74),
				job_id: 'demo-job-8019',
				node_id: 'demo-node-4',
				model: MOCK_MODELS[3].hf_id,
				output_tokens: 132
			},
			{
				type: 'job_started',
				created_at: isoOffset(105),
				node_id: 'demo-node-2',
				job_id: 'demo-job-8017',
				model: `${MOCK_MODELS[2].hf_id} • warming cache`
			}
		]
	};
}

export function tickMockStats(stats: Stats, step: number): Stats {
	const jobsRunning = 3 + ((step * 5) % 7);
	return {
		nodes_online: 11,
		jobs_running: jobsRunning,
		tokens_total: currentMockTokensTotal(),
		tokens_per_second: Number((142 + ((step * 11) % 34) + jobsRunning * 6.7).toFixed(1))
	};
}

export function tickMockModels(models: ModelRow[], step: number): ModelRow[] {
	return models.map((model, index) => ({
		...model,
		node_count: Math.max(1, model.node_count + (((step + index) % 3) - 1))
	}));
}

export function tickMockLeaders(leaders: Leader[], step: number): Leader[] {
	return leaders.map((leader, index) => {
		const nextSubcredits = leader.credits_earned_subcredits + (step + index + 1) * 47;
		return {
			...leader,
			credits_earned_subcredits: nextSubcredits,
			credits_earned: formatSubcredits(nextSubcredits)
		};
	});
}

export function nextMockEvent(step: number): EventRow {
	return createEvent(step);
}
