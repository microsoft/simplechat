---
layout: showcase-page
title: "How-To Guides"
permalink: /how-to/
menubar: docs_menu
accent: teal
eyebrow: "Task-Oriented Guidance"
description: "Use the how-to section for practical workflows after the platform is already understood: uploads, agents, identity, scaling, upgrades, networking, and external integrations."
hero_icons: ["bi-tools", "bi-signpost-split", "bi-check2-square"]
hero_pills: ["Repeatable operator tasks", "Platform and integration workflows", "Shorter than full reference pages"]
hero_links: [{ label: "Tutorials", url: "/tutorials/", style: "primary" }, { label: "Reference section", url: "/reference/", style: "secondary" }]
---

How-to guides assume you already know what area of the product you are working in. They focus on practical execution: the steps, dependencies, and validation checks needed to complete a specific task.

<section class="latest-release-card-grid">
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-file-earmark-arrow-up"></i></div>
        <h2>Content and agents</h2>
        <p>Add documents, create agents, and use the ServiceNow agent guides when your work is centered on user workflows and external system actions.</p>
        <p><a href="{{ '/how-to/add_documents/' | relative_url }}">Add documents</a> · <a href="{{ '/how-to/create_agents/' | relative_url }}">Create agents</a> · <a href="{{ '/how-to/agents/ServiceNow/' | relative_url }}">ServiceNow guides</a></p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-person-badge"></i></div>
        <h2>Identity and security</h2>
        <p>Use the managed identity and Azure Speech guides when you want to replace stored secrets or handle service-specific authentication correctly.</p>
        <p><a href="{{ '/how-to/use_managed_identity/' | relative_url }}">Managed identity</a> · <a href="{{ '/how-to/azure_speech_managed_identity_manul_setup/' | relative_url }}">Azure Speech setup</a></p>
    </article>
    <article class="latest-release-card">
        <div class="latest-release-card-icon"><i class="bi bi-diagram-3"></i></div>
        <h2>Deployment operations</h2>
        <p>Use these guides for enterprise networking, scaling, upgrades, and Docker customization once the deployment starts moving toward production operations.</p>
        <p><a href="{{ '/how-to/enterprise_networking/' | relative_url }}">Enterprise networking</a> · <a href="{{ '/how-to/scaling_on_azure/' | relative_url }}">Scaling</a> · <a href="{{ '/how-to/upgrade_paths/' | relative_url }}">Upgrade paths</a></p>
    </article>
</section>

<div class="latest-release-note-panel">
    <h2>Choose the shortest path that solves the task</h2>
    <p>If you need conceptual background, switch to the explanation pages. If you need exact settings or route details, switch to the reference pages. Stay in the how-to section when the task itself is already clear and you want the execution sequence.</p>
</div>