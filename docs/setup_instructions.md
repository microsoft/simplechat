---
layout: showcase-page
title: "Getting Started"
description: "Choose the right deployment path, line up the prerequisites, and follow the repo's recommended rollout order for Simple Chat."
section: "Tutorials"
accent: emerald
eyebrow: "Deployment Guide"
hero_icons:
  - bi-rocket-takeoff
  - bi-cloud-arrow-up
  - bi-sliders2
hero_pills:
  - "Recommended path: azd up"
  - Container-first deployers
  - Native Python fallback available
hero_links:
  - label: "Open AZD deployment guide"
    url: /reference/deploy/azd-cli_deploy/
    style: primary
  - label: "Review upgrade paths"
    url: /how-to/upgrade_paths/
    style: outline
nav_links:
  next:
    title: "Manual Setup"
    url: /setup_instructions_manual/
---

If you want the most current, least ambiguous deployment path, start with Azure Developer CLI and run `azd up`. The rest of the deployment options exist to match different operating models, not because they are all equally preferred.

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Choose your path</div>
      <h2>Deployment options in recommended order</h2>
      <p>All of these paths are supported, but they differ in how much automation, flexibility, and operational context they give you.</p>
    </div>
    <span class="latest-release-section-badge">Most used first</span>
  </div>

  <div class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--emerald">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-rocket-takeoff"></i></span>
          <span class="latest-release-card-badge">Recommended</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/reference/deploy/azd-cli_deploy/' | relative_url }}">Azure Developer CLI</a></h3>
        <p class="latest-release-card-summary">Use this when you want the smoothest repo-supported experience. It provisions infrastructure, packages the app, and deploys it through the same workflow.</p>
        <div class="latest-release-card-why">
          <div class="latest-release-card-why-label">Why it matters</div>
          <p class="mb-0">This is the path reflected across the main README and the current deployment documentation.</p>
        </div>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/reference/deploy/azd-cli_deploy/' | relative_url }}">Read AZD guide</a>
        </div>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--blue">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-terminal"></i></span>
          <span class="latest-release-card-badge">Scripted</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/reference/deploy/azurecli_powershell_deploy/' | relative_url }}">Azure CLI with PowerShell</a></h3>
        <p class="latest-release-card-summary">Use this when you want more direct control over sequencing, recovery steps, and script-driven operations without moving to a fully manual deployment.</p>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/reference/deploy/azurecli_powershell_deploy/' | relative_url }}">Read Azure CLI guide</a>
        </div>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--orange">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-diagram-3"></i></span>
          <span class="latest-release-card-badge">IaC</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/reference/deploy/bicep_deploy/' | relative_url }}">Bicep</a></h3>
        <p class="latest-release-card-summary">Use Bicep when you want to inspect or customize the infrastructure modules directly. It is the same IaC layer that the AZD path builds on.</p>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/reference/deploy/bicep_deploy/' | relative_url }}">Inspect Bicep flow</a>
        </div>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--slate">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-box-seam"></i></span>
          <span class="latest-release-card-badge">Alternative</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/reference/deploy/terraform_deploy/' | relative_url }}">Terraform</a></h3>
        <p class="latest-release-card-summary">Use Terraform when it is already the standard in your environment and you are comfortable handling image publishing as part of the rollout.</p>
        <div class="latest-release-card-actions">
          <a class="btn btn-primary btn-sm" href="{{ '/reference/deploy/terraform_deploy/' | relative_url }}">Review Terraform guide</a>
        </div>
      </div>
    </article>
  </div>
</section>

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Recommended flow</div>
      <h2>What a clean first deployment looks like</h2>
      <p>These four steps keep you aligned with the repo's expectations and reduce the chance of backtracking later.</p>
    </div>
    <span class="latest-release-section-badge">Step by step</span>
  </div>

  <div class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--emerald">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-1-circle"></i></span>
          <span class="latest-release-card-badge">Step 1</span>
        </div>
        <h3 class="latest-release-card-title">Prepare access</h3>
        <p class="latest-release-card-summary">Confirm Azure subscription permissions, app registration creation rights, and access to container build resources before you begin.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--blue">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-2-circle"></i></span>
          <span class="latest-release-card-badge">Step 2</span>
        </div>
        <h3 class="latest-release-card-title">Choose the deployer</h3>
        <p class="latest-release-card-summary">Default to AZD unless your environment already depends on a different provisioning workflow or you need native Python deployment details.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--orange">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-3-circle"></i></span>
          <span class="latest-release-card-badge">Step 3</span>
        </div>
        <h3 class="latest-release-card-title">Deploy infrastructure and app</h3>
        <p class="latest-release-card-summary">Run the chosen workflow end to end so the app service, identity, storage, search, and runtime expectations stay in sync.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--slate">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-4-circle"></i></span>
          <span class="latest-release-card-badge">Step 4</span>
        </div>
        <h3 class="latest-release-card-title">Plan the upgrade path</h3>
        <p class="latest-release-card-summary">Once the first environment is live, switch to the dedicated upgrade guidance for updates instead of replaying the initial setup flow.</p>
      </div>
    </article>
  </div>
</section>

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Prerequisites</div>
      <h2>What to line up before you run anything</h2>
      <p>Most failed first deployments come from missing access, not from the deployer itself.</p>
    </div>
    <span class="latest-release-section-badge">Read once</span>
  </div>

  <div class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--teal">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-person-check"></i></span>
          <span class="latest-release-card-badge">Access</span>
        </div>
        <h3 class="latest-release-card-title">Azure and identity permissions</h3>
        <p class="latest-release-card-summary">You need subscription-level deployment rights plus the ability to create or coordinate an Entra application registration for the app.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--orange">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-tools"></i></span>
          <span class="latest-release-card-badge">Tooling</span>
        </div>
        <h3 class="latest-release-card-title">Install the local toolchain</h3>
        <p class="latest-release-card-summary">At minimum, line up Azure CLI, Azure Developer CLI, PowerShell 7, and Visual Studio Code before starting the primary flow.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--slate">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-building-gear"></i></span>
          <span class="latest-release-card-badge">Platform model</span>
        </div>
        <h3 class="latest-release-card-title">Know whether you need exceptions</h3>
        <p class="latest-release-card-summary">If you need sovereign cloud support, private networking, managed identity-specific configuration, or native Python hosting, review the related docs before deploying.</p>
      </div>
    </article>
  </div>
</section>

<section class="latest-release-section">
  <div class="latest-release-section-header">
    <div>
      <div class="latest-release-section-kicker">Next steps</div>
      <h2>Use the follow-on guides when the default path is not enough</h2>
      <p>These documents sit alongside the main setup flow instead of replacing it.</p>
    </div>
    <span class="latest-release-section-badge">Related guides</span>
  </div>

  <div class="latest-release-card-grid">
    <article class="latest-release-card latest-release-accent--blue">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-wrench-adjustable-circle"></i></span>
          <span class="latest-release-card-badge">Detailed setup</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/setup_instructions_manual/' | relative_url }}">Manual deployment</a></h3>
        <p class="latest-release-card-summary">Use this for native Python App Service deployments or when you need the lower-level configuration path spelled out.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--orange">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-signpost-split"></i></span>
          <span class="latest-release-card-badge">Scenarios</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/setup_instructions_special/' | relative_url }}">Special deployment scenarios</a></h3>
        <p class="latest-release-card-summary">Review guidance for Azure Government, managed identities, enterprise networking, and other non-default rollout patterns.</p>
      </div>
    </article>

    <article class="latest-release-card latest-release-accent--slate">
      <div class="latest-release-card-shell">
        <div class="latest-release-card-top">
          <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-arrow-repeat"></i></span>
          <span class="latest-release-card-badge">Operations</span>
        </div>
        <h3 class="latest-release-card-title"><a href="{{ '/how-to/upgrade_paths/' | relative_url }}">Upgrade existing deployments</a></h3>
        <p class="latest-release-card-summary">Once you are live, use the upgrade guide to decide between code-only, image-only, and infrastructure-aware updates.</p>
      </div>
    </article>
  </div>
</section>