---
layout: latest-release-index
title: "Latest Release Highlights"
description: "Current feature guides with previous release highlights kept for reference"
section: "Latest Release"
---

{% assign feature_data = site.data.latest_release_features %}

<section class="latest-release-section">
	<div class="latest-release-section-header">
		<div>
			<div class="latest-release-section-kicker">Current release</div>
			<h2>{{ feature_data.current_release.label }}</h2>
			<p>{{ feature_data.current_release.description }}</p>
		</div>
		<span class="latest-release-section-badge">{{ feature_data.current_release.badge }}</span>
	</div>

	<div class="latest-release-card-grid">
		{% for slug in feature_data.current_release.slugs %}
			{% assign feature = feature_data.lookup[slug] %}
			{% include latest_release_card.html feature=feature badge=feature_data.current_release.badge %}
		{% endfor %}
	</div>
</section>

{% for group in feature_data.previous_release_groups %}
	<details class="latest-release-archive-panel">
		<summary>
			<span class="latest-release-archive-summary-copy">
				<span class="latest-release-section-kicker">Archive</span>
				<strong>{{ group.label }}</strong>
				<small>{{ group.description }}</small>
			</span>

			<span class="latest-release-archive-toggle">
				<span class="latest-release-archive-version">v{{ group.release_version }}</span>
				<span class="latest-release-archive-toggle-text">Show highlights</span>
			</span>
		</summary>

		<div class="latest-release-archive-body">
			<div class="latest-release-card-grid">
				{% for slug in group.slugs %}
					{% assign feature = feature_data.lookup[slug] %}
					{% include latest_release_card.html feature=feature badge=group.badge %}
				{% endfor %}
			</div>

			{% if group.highlights %}
				<div class="latest-release-note-panel">
					<h3>Additional highlights from v{{ group.release_version }}</h3>
					<ul>
						{% for item in group.highlights %}
							<li>{{ item }}</li>
						{% endfor %}
					</ul>
				</div>
			{% endif %}

			{% if group.bug_fixes %}
				<div class="latest-release-note-panel latest-release-note-panel--subtle">
					<h3>Bug fixes kept for reference</h3>
					<ul>
						{% for item in group.bug_fixes %}
							<li>{{ item }}</li>
						{% endfor %}
					</ul>
				</div>
			{% endif %}
		</div>
	</details>
{% endfor %}

<div class="latest-release-footer-note">
	For deeper technical detail, use the [Release Notes]({{ '/explanation/release_notes/' | relative_url }}) alongside the feature guides above.
</div>
