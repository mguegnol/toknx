<script lang="ts">
	import { browser } from '$app/environment';
	import type { EventRow, Leader, ModelRow, Stats } from '$lib/types';

	export let data: {
		apiBase: string;
		stats: Stats;
		models: ModelRow[];
		leaders: Leader[];
	};

	let stats = data.stats;
	let models = data.models;
	let leaders = data.leaders;
	let events: EventRow[] = [];

	if (browser) {
		const source = new EventSource(`${data.apiBase}/events/stream`);
		source.onmessage = (event) => {
			const parsed = JSON.parse(event.data) as EventRow;
			events = [parsed, ...events].slice(0, 24);
		};
	}
</script>

<svelte:head>
	<title>ToknX</title>
	<meta
		name="description"
		content="Contribute idle Apple Silicon hardware. Earn LLM tokens. ToknX is a compute co-op for inference."
	/>
</svelte:head>

<div class="shell">
	<section class="hero">
		<p class="eyebrow">ToknX</p>
		<h1>A compute co-op for Apple Silicon.</h1>
		<p class="lede">
			Contribute idle Mac hardware, earn credits, and spend them on code generation through an
			OpenAI-compatible API.
		</p>
		<div class="actions">
			<a href={`${data.apiBase}/auth/github?username=localdev`} class="primary">Sign up with GitHub</a>
			<a href="https://github.com" class="secondary">Contribute a node</a>
		</div>
	</section>

	<section class="stats-grid">
		<article>
			<span>Nodes online</span>
			<strong>{stats.nodes_online}</strong>
		</article>
		<article>
			<span>Jobs running</span>
			<strong>{stats.jobs_running}</strong>
		</article>
		<article>
			<span>Tokens generated</span>
			<strong>{stats.tokens_total.toLocaleString()}</strong>
		</article>
		<article>
			<span>Network throughput</span>
			<strong>{stats.tokens_per_second} tok/s</strong>
		</article>
	</section>

	<div class="content-grid">
		<section class="panel">
			<div class="panel-header">
				<h2>Models available now</h2>
				<p>Live inventory from online contributor nodes.</p>
			</div>
			<div class="rows">
				{#if models.length}
					{#each models as model}
						<div class="row">
							<div>
								<strong>{model.hf_id}</strong>
								<span>{model.estimated_ram_gb} GB estimated RAM</span>
							</div>
							<div class="row-meta">
								<span>{model.node_count} nodes</span>
								<span>Tier {model.pricing_tier}</span>
								<span>{model.credits_per_1k_tokens} cr / 1K</span>
							</div>
						</div>
					{/each}
				{:else}
					<p class="empty">No nodes are online yet.</p>
				{/if}
			</div>
		</section>

		<section class="panel">
			<div class="panel-header">
				<h2>Live activity</h2>
				<p>Streaming network events over SSE.</p>
			</div>
			<div class="rows activity">
				{#if events.length}
					{#each events as event}
						<div class="event-row">
							<time>{new Date(event.created_at).toLocaleTimeString()}</time>
							<div>
								<strong>{event.type.replace('_', ' ')}</strong>
								<span>{event.models?.join(', ') ?? event.hardware?.chip ?? 'network event'}</span>
							</div>
						</div>
					{/each}
				{:else}
					<p class="empty">Waiting for the first event.</p>
				{/if}
			</div>
		</section>
	</div>

	<section class="panel leaderboard">
		<div class="panel-header">
			<h2>Top contributors (7d)</h2>
			<p>Credits earned from completed jobs.</p>
		</div>
		<div class="rows">
			{#if leaders.length}
				{#each leaders as leader, index}
					<div class="row">
						<div>
							<strong>{index + 1}. @{leader.github_username}</strong>
							<span>Contributor</span>
						</div>
						<div class="row-meta">
							<span>{leader.credits_earned.toLocaleString()} credits</span>
						</div>
					</div>
				{/each}
			{:else}
				<p class="empty">Leaderboard fills as jobs complete.</p>
			{/if}
		</div>
	</section>
</div>

<style>
	:global(body) {
		margin: 0;
		font-family: 'IBM Plex Sans', 'Avenir Next', sans-serif;
		background:
			radial-gradient(circle at top left, rgba(0, 168, 150, 0.22), transparent 28%),
			radial-gradient(circle at top right, rgba(255, 157, 0, 0.18), transparent 22%),
			#0d1516;
		color: #f5f2eb;
	}

	.shell {
		max-width: 1180px;
		margin: 0 auto;
		padding: 48px 20px 72px;
	}

	.hero {
		padding: 28px;
		border: 1px solid rgba(245, 242, 235, 0.12);
		background: rgba(8, 12, 13, 0.75);
		backdrop-filter: blur(10px);
	}

	.eyebrow {
		text-transform: uppercase;
		letter-spacing: 0.16em;
		color: #7ed8cb;
		font-size: 0.78rem;
	}

	h1,
	h2,
	strong {
		font-family: 'IBM Plex Mono', 'SFMono-Regular', monospace;
	}

	h1 {
		font-size: clamp(2.4rem, 6vw, 5rem);
		margin: 0.3rem 0 0.7rem;
		line-height: 0.95;
		max-width: 11ch;
	}

	.lede {
		max-width: 52rem;
		font-size: 1.1rem;
		color: #d2ddd8;
	}

	.actions {
		display: flex;
		gap: 12px;
		flex-wrap: wrap;
		margin-top: 22px;
	}

	.actions a {
		text-decoration: none;
		padding: 12px 18px;
		border-radius: 999px;
		font-weight: 700;
	}

	.primary {
		background: #7ed8cb;
		color: #081010;
	}

	.secondary {
		border: 1px solid rgba(245, 242, 235, 0.2);
		color: #f5f2eb;
	}

	.stats-grid,
	.content-grid {
		display: grid;
		gap: 18px;
		margin-top: 22px;
	}

	.stats-grid {
		grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
	}

	.stats-grid article,
	.panel {
		border: 1px solid rgba(245, 242, 235, 0.12);
		background: rgba(8, 12, 13, 0.72);
		padding: 20px;
	}

	.stats-grid article span,
	.panel-header p,
	.row span,
	.empty,
	time {
		color: #b0beb9;
	}

	.stats-grid strong {
		display: block;
		font-size: 2rem;
		margin-top: 8px;
	}

	.content-grid {
		grid-template-columns: 1.2fr 0.8fr;
	}

	.panel-header {
		margin-bottom: 14px;
	}

	.panel-header h2 {
		margin: 0;
		font-size: 1.2rem;
	}

	.rows {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.row,
	.event-row {
		display: flex;
		justify-content: space-between;
		gap: 18px;
		padding-top: 12px;
		border-top: 1px solid rgba(245, 242, 235, 0.08);
	}

	.row:first-child,
	.event-row:first-child {
		padding-top: 0;
		border-top: 0;
	}

	.row strong,
	.event-row strong {
		display: block;
	}

	.row-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 10px;
		justify-content: flex-end;
		text-align: right;
	}

	.activity {
		max-height: 460px;
		overflow: auto;
	}

	.leaderboard {
		margin-top: 22px;
	}

	@media (max-width: 860px) {
		.content-grid {
			grid-template-columns: 1fr;
		}

		.row,
		.event-row {
			flex-direction: column;
		}

		.row-meta {
			justify-content: flex-start;
			text-align: left;
		}
	}
</style>

