---
layout: showcase-page
title: "Add Documents"
permalink: /how-to/add_documents/
menubar: docs_menu
accent: blue
eyebrow: "How-To Guide"
description: "Use this guide when you need a practical, repeatable workflow for adding files to personal, group, or public workspaces and making them searchable."
hero_icons:
  - bi-file-earmark-arrow-up
  - bi-folder2-open
  - bi-search
hero_pills:
  - Personal, group, and public scopes
  - Searchable after processing completes
  - Classification and citations supported
hero_links:
  - label: "Document tutorial"
    url: /tutorials/uploading_documents/
    style: primary
  - label: "Admin overview"
    url: /admin_configuration/
    style: secondary
---

Treat uploads as an ingestion workflow, not just a file transfer. The target workspace, enabled services, and metadata choices determine whether the file becomes grounded chat context, searchable workspace content, or an item waiting on a missing dependency.

<section class="latest-release-card-grid">
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-folder2-open"></i></div>
				<h2>Choose the right workspace</h2>
				<p>Upload into the personal, group, or public scope that matches who should discover and cite the file later.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-file-earmark-check"></i></div>
				<h2>Prepare a clean source file</h2>
				<p>Clear filenames, readable text, and well-structured documents make extraction, chunking, and retrieval more reliable.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-hourglass-split"></i></div>
				<h2>Wait for processing to finish</h2>
				<p>Uploads are only useful for grounding after extraction, indexing, and metadata processing complete successfully.</p>
		</article>
		<article class="latest-release-card">
				<div class="latest-release-card-icon"><i class="bi bi-check2-square"></i></div>
				<h2>Verify searchability</h2>
				<p>Test retrieval from the workspace UI or chat flow so you know the document is ready before relying on it in user workflows.</p>
		</article>
</section>

<div class="latest-release-note-panel">
		<h2>Uploads depend on the search and extraction stack</h2>
		<p>If workspace grounding is enabled, document ingestion usually depends on embeddings, Azure AI Search, and Document Intelligence being configured correctly. Optional features like enhanced citations, speech, or video support add more dependencies on top of that core path.</p>
</div>

## Recommended upload flow

1. Pick the destination workspace based on who should be able to discover the file.
2. Confirm the file type is supported and the document is readable enough for extraction.
3. Upload the file and watch for processing completion in the workspace experience.
4. Add or verify metadata such as classification, title, or extraction results when your environment uses them.
5. Run a search or grounded chat prompt to confirm the document is discoverable.

## Metadata choices that improve retrieval

- Use descriptive filenames so citations are meaningful.
- Apply document classification when the workspace relies on category-based filtering.
- Review extracted fields if the environment surfaces metadata extraction results.
- Keep duplicates and outdated copies under control so retrieval does not split relevance across nearly identical files.

## When a file uploads but does not show up in chat

- Verify the workspace type you uploaded to matches the scope you are searching.
- Confirm the document finished processing rather than remaining in an in-progress or failed state.
- Check that embeddings, Azure AI Search, and Document Intelligence are configured if the environment uses grounded retrieval.
- Review the admin settings for file-type restrictions, classification requirements, or disabled workspace features.

## Related guides

- [Uploading and Managing Documents](../tutorials/uploading_documents.md)
- [Document Classification Tutorial](../tutorials/classifying_documents.md)
- [Application Workflows](../application_workflows.md)
- [Troubleshooting](../troubleshooting/troubleshooting.md)
