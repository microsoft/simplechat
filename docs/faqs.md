---
layout: showcase-page
title: "FAQ"
description: "Answers to the questions that come up most often when teams deploy, secure, and operate Simple Chat in Azure environments."
section: "Support"
accent: slate
eyebrow: "Troubleshooting"
hero_icons:
  - bi-question-circle
  - bi-shield-lock
  - bi-search
hero_pills:
  - Networking and firewall issues
  - Identity and model setup
  - Upload and retrieval troubleshooting
hero_links:
  - label: "Getting Started"
    url: /setup_instructions/
    style: primary
  - label: "Review features"
    url: /features/
    style: outline
---

Use this page as the fast triage layer: it focuses on the recurring questions that show up after a team has already deployed or started hardening the environment.

<section class="latest-release-section">
   <div class="latest-release-section-header">
      <div>
         <div class="latest-release-section-kicker">Quick jump</div>
         <h2>Start with the category that matches the failure mode</h2>
         <p>Each card jumps to the section where the most likely causes and checks are grouped together.</p>
      </div>
      <span class="latest-release-section-badge">Top issues</span>
   </div>

   <div class="latest-release-card-grid">
      <article class="latest-release-card latest-release-accent--orange">
         <div class="latest-release-card-shell">
            <div class="latest-release-card-top">
               <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-shield-lock"></i></span>
               <span class="latest-release-card-badge">Network</span>
            </div>
            <h3 class="latest-release-card-title"><a href="#networking-and-firewalls">Firewall and private endpoint issues</a></h3>
            <p class="latest-release-card-summary">Start here when uploads, search, or admin actions break only after the app is placed behind a firewall, WAF, or private network boundary.</p>
         </div>
      </article>

      <article class="latest-release-card latest-release-accent--blue">
         <div class="latest-release-card-shell">
            <div class="latest-release-card-top">
               <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-person-lock"></i></span>
               <span class="latest-release-card-badge">Identity</span>
            </div>
            <h3 class="latest-release-card-title"><a href="#authentication-and-access">Authentication and access</a></h3>
            <p class="latest-release-card-summary">Use this section when users cannot sign in, role assignments do not behave as expected, or model enumeration fails because of tenant boundaries.</p>
         </div>
      </article>

      <article class="latest-release-card latest-release-accent--emerald">
         <div class="latest-release-card-shell">
            <div class="latest-release-card-top">
               <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-cloud-upload"></i></span>
               <span class="latest-release-card-badge">Ingestion</span>
            </div>
            <h3 class="latest-release-card-title"><a href="#uploads-and-search">Uploads and retrieval</a></h3>
            <p class="latest-release-card-summary">Use this path when files fail during processing, indexes stay empty, or grounded answers are missing expected source material.</p>
         </div>
      </article>

      <article class="latest-release-card latest-release-accent--slate">
         <div class="latest-release-card-shell">
            <div class="latest-release-card-top">
               <span class="latest-release-card-icon" aria-hidden="true"><i class="bi bi-sliders2"></i></span>
               <span class="latest-release-card-badge">Configuration</span>
            </div>
            <h3 class="latest-release-card-title"><a href="#model-configuration">Model and endpoint configuration</a></h3>
            <p class="latest-release-card-summary">Use this section when GPT, embeddings, DALL-E, or APIM-mode settings are the part of the system that is behaving unexpectedly.</p>
         </div>
      </article>
   </div>
</section>

<div id="networking-and-firewalls"></div>

<section class="latest-release-section">
   <div class="latest-release-section-header">
      <div>
         <div class="latest-release-section-kicker">Network</div>
         <h2>Firewall and private endpoint questions</h2>
         <p>These issues usually surface after the app is moved behind network controls that only allow a subset of browser or outbound service traffic.</p>
      </div>
      <span class="latest-release-section-badge">Connectivity</span>
   </div>

   <details class="latest-release-archive-panel" open>
      <summary>
         <span class="latest-release-archive-summary-copy">
            <span class="latest-release-section-kicker">Q1</span>
            <strong>We put Simple Chat behind a firewall or WAF and uploads, search, or admin updates stopped working.</strong>
            <small>The browser still needs to reach the backend API routes that power the app.</small>
         </span>
         <span class="latest-release-archive-toggle">
            <span class="latest-release-archive-version">API traffic</span>
            <span class="latest-release-archive-toggle-text">Open answer</span>
         </span>
      </summary>
      <div class="latest-release-archive-body">
         <div class="latest-release-note-panel latest-release-accent--orange">
            <h3>What to verify</h3>
            <ul>
               <li>Simple Chat serves a frontend in the browser and a backend API from the app service, so blocking `/api/*` traffic breaks core features even when the page shell still loads.</li>
               <li>Allow browser-originated `GET`, `POST`, `PUT`, `PATCH`, and `DELETE` calls to your app service API routes.</li>
               <li>Use the repository OpenAPI specification under `artifacts/open_api/openapi.yaml` to understand which endpoints the frontend depends on.</li>
            </ul>
         </div>
      </div>
   </details>

   <details class="latest-release-archive-panel">
      <summary>
         <span class="latest-release-archive-summary-copy">
            <span class="latest-release-section-kicker">Q2</span>
            <strong>Can I use Azure OpenAI and related services through private endpoints?</strong>
            <small>Yes, but the app service must be able to resolve and reach those private addresses.</small>
         </span>
         <span class="latest-release-archive-toggle">
            <span class="latest-release-archive-version">Private networking</span>
            <span class="latest-release-archive-toggle-text">Open answer</span>
         </span>
      </summary>
      <div class="latest-release-archive-body">
         <div class="latest-release-note-panel latest-release-accent--slate">
            <h3>What to verify</h3>
            <ul>
               <li>Integrate the app service with a VNet that can reach the private endpoints for Azure OpenAI, AI Search, Cosmos DB, Storage, and any other required service.</li>
               <li>Make sure private DNS zones or custom DNS resolve those endpoints to the expected private IP addresses.</li>
               <li>Validate outbound connectivity from the app service, not just from an admin workstation.</li>
            </ul>
         </div>
      </div>
   </details>
</section>

<div id="authentication-and-access"></div>

<section class="latest-release-section">
   <div class="latest-release-section-header">
      <div>
         <div class="latest-release-section-kicker">Identity</div>
         <h2>Authentication and access questions</h2>
         <p>When sign-in or model management fails, start by confirming the identity plane before you assume the app itself is broken.</p>
      </div>
      <span class="latest-release-section-badge">Entra ID</span>
   </div>

   <details class="latest-release-archive-panel">
      <summary>
         <span class="latest-release-archive-summary-copy">
            <span class="latest-release-section-kicker">Q3</span>
            <strong>Users are getting authentication errors or cannot log in.</strong>
            <small>Most login failures come from app registration or assignment drift.</small>
         </span>
         <span class="latest-release-archive-toggle">
            <span class="latest-release-archive-version">Access checks</span>
            <span class="latest-release-archive-toggle-text">Open answer</span>
         </span>
      </summary>
      <div class="latest-release-archive-body">
         <div class="latest-release-note-panel latest-release-accent--blue">
            <h3>What to verify</h3>
            <ul>
               <li>The redirect URI for `/.auth/login/aad/callback` is configured correctly in the Entra app registration.</li>
               <li>App Service Authentication is enabled, points at the correct app registration, and is set to require authentication.</li>
               <li>Users or groups are assigned to the enterprise application when assignment is required.</li>
               <li>Microsoft Graph permissions such as `User.Read`, `openid`, and `profile` are configured and have admin consent.</li>
               <li>`TENANT_ID` and `CLIENT_ID` values in the app settings match the intended tenant and application.</li>
            </ul>
         </div>
      </div>
   </details>

   <details class="latest-release-archive-panel">
      <summary>
         <span class="latest-release-archive-summary-copy">
            <span class="latest-release-section-kicker">Q4</span>
            <strong>Fetch Models fails when the authentication app registration is in a different tenant than Azure OpenAI.</strong>
            <small>The data plane can still work even when cross-tenant management-plane model listing is blocked.</small>
         </span>
         <span class="latest-release-archive-toggle">
            <span class="latest-release-archive-version">Cross-tenant</span>
            <span class="latest-release-archive-toggle-text">Open answer</span>
         </span>
      </summary>
      <div class="latest-release-archive-body">
         <div class="latest-release-note-panel latest-release-accent--orange">
            <h3>Workaround</h3>
            <ol>
               <li>In Admin Settings under GPT, enable <strong>Use APIM instead of direct to Azure OpenAI endpoint</strong>.</li>
               <li>Enter the Azure OpenAI endpoint URL, API version, and deployment name in the APIM fields instead of a true APIM proxy.</li>
               <li>Save the settings and fetch models again.</li>
            </ol>
            <p class="mb-0">That route shifts model listing into the APIM-mode flow and avoids the cross-tenant management-plane enumeration failure.</p>
         </div>
         <img src="{{ '/images/cross_tenant-model_support.png' | relative_url }}" alt="Cross-tenant model support guidance screenshot." />
      </div>
   </details>
</section>

<div id="uploads-and-search"></div>

<section class="latest-release-section">
   <div class="latest-release-section-header">
      <div>
         <div class="latest-release-section-kicker">Ingestion and retrieval</div>
         <h2>Upload and search questions</h2>
         <p>These problems usually come from permission gaps, failed indexing, or missing model configuration for embeddings and extraction.</p>
      </div>
      <span class="latest-release-section-badge">Grounding</span>
   </div>

   <details class="latest-release-archive-panel">
      <summary>
         <span class="latest-release-archive-summary-copy">
            <span class="latest-release-section-kicker">Q5</span>
            <strong>File uploads are failing.</strong>
            <small>Start by checking the dependent services the pipeline writes to during ingestion.</small>
         </span>
         <span class="latest-release-archive-toggle">
            <span class="latest-release-archive-version">Uploads</span>
            <span class="latest-release-archive-toggle-text">Open answer</span>
         </span>
      </summary>
      <div class="latest-release-archive-body">
         <div class="latest-release-note-panel latest-release-accent--emerald">
            <h3>What to verify</h3>
            <ul>
               <li>The app service has permission to reach AI Search, Document Intelligence, Storage, Speech, Video Indexer, and any other enabled service in the upload path.</li>
               <li>Managed identity role assignments or configured keys are valid and match the services you enabled.</li>
               <li>Application Insights and App Service logs show whether the failure happens during extraction, embedding, indexing, or storage.</li>
               <li>File Processing Logs in Admin Settings can expose the exact stage that failed.</li>
            </ul>
         </div>
      </div>
   </details>

   <details class="latest-release-archive-panel">
      <summary>
         <span class="latest-release-archive-summary-copy">
            <span class="latest-release-section-kicker">Q6</span>
            <strong>RAG is not returning expected results or any results.</strong>
            <small>When search quality drops, verify indexing and embeddings before tuning prompts.</small>
         </span>
         <span class="latest-release-archive-toggle">
            <span class="latest-release-archive-version">Search</span>
            <span class="latest-release-archive-toggle-text">Open answer</span>
         </span>
      </summary>
      <div class="latest-release-archive-body">
         <div class="latest-release-note-panel latest-release-accent--teal">
            <h3>What to verify</h3>
            <ul>
               <li>Uploaded documents finished processing successfully in the workspace UI.</li>
               <li>The relevant Azure AI Search index contains the documents you expect and its count increases after uploads.</li>
               <li>The embedding deployment is configured correctly and reachable from the application.</li>
               <li>The Search Documents toggle is enabled in the chat UI and the user question is phrased in a way that maps to indexed content.</li>
            </ul>
         </div>
      </div>
   </details>
</section>

<div id="model-configuration"></div>

<section class="latest-release-section">
   <div class="latest-release-section-header">
      <div>
         <div class="latest-release-section-kicker">Configuration</div>
         <h2>Model management questions</h2>
         <p>These checks matter when the application loads but the configured AI capabilities do not behave the way you expect.</p>
      </div>
      <span class="latest-release-section-badge">Admin settings</span>
   </div>

   <details class="latest-release-archive-panel">
      <summary>
         <span class="latest-release-archive-summary-copy">
            <span class="latest-release-section-kicker">Q7</span>
            <strong>How do I update the GPT, embedding, or DALL-E models used by the application?</strong>
            <small>Model selection is handled through admin configuration rather than code deployment.</small>
         </span>
         <span class="latest-release-archive-toggle">
            <span class="latest-release-archive-version">Model updates</span>
            <span class="latest-release-archive-toggle-text">Open answer</span>
         </span>
      </summary>
      <div class="latest-release-archive-body">
         <div class="latest-release-note-panel latest-release-accent--slate">
            <h3>What to do</h3>
            <ul>
               <li>Open <strong>Admin Settings</strong>.</li>
               <li>Go to the GPT, Embeddings, or Image Generation section that matches the model you want to change.</li>
               <li>Fetch the available deployments from the configured Azure OpenAI endpoint and select the desired deployment name.</li>
               <li>Save the settings. A code redeploy is not required when the endpoint stays the same.</li>
            </ul>
         </div>
      </div>
   </details>
</section>
