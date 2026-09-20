// workflowFlowLayout.ts
// Deterministic display geometry; never writes an executable workflow definition.

import type { WorkflowFlowProjection, WorkflowInspectionEdge, WorkflowInspectionNode } from './workflowInspection';

export interface WorkflowFlowBox {
    id: string;
    parentId?: string;
    position: { x: number; y: number };
    width: number;
    height: number;
    container: boolean;
}

const PADDING = 24;
const HEADER = 92;
const GAP = 54;
const WIDTH = 280;
const HEIGHT = 116;

function childrenByParent(nodes: WorkflowInspectionNode[]): Map<string, WorkflowInspectionNode[]> {
    const children = new Map<string, WorkflowInspectionNode[]>();
    for (const node of nodes) {
        if (node.parent_id === null) continue;
        const siblings = children.get(node.parent_id) ?? [];
        siblings.push(node);
        children.set(node.parent_id, siblings);
    }
    for (const siblings of children.values()) siblings.sort((left, right) => left.order - right.order || left.id.localeCompare(right.id));
    return children;
}

export function layoutWorkflowFlow(projection: WorkflowFlowProjection, collapsed: ReadonlySet<string>): WorkflowFlowBox[] {
    const children = childrenByParent(projection.nodes);
    const byId = new Map(projection.nodes.map((node) => [node.id, node]));
    const sizes = new Map<string, { width: number; height: number }>();
    const measure = (node: WorkflowInspectionNode): { width: number; height: number } => {
        const descendants = collapsed.has(node.id) ? [] : children.get(node.id) ?? [];
        const horizontal = node.kind === 'if';
        const measured = descendants.map(measure);
        const size = !measured.length ? { width: WIDTH, height: HEIGHT } : {
            width: (horizontal
                ? measured.reduce((sum, child) => sum + child.width, 0) + GAP * (measured.length - 1)
                : Math.max(...measured.map((child) => child.width))) + PADDING * 2,
            height: (horizontal
                ? Math.max(...measured.map((child) => child.height))
                : measured.reduce((sum, child) => sum + child.height, 0) + GAP * (measured.length - 1)) + HEADER + PADDING,
        };
        sizes.set(node.id, size);
        return size;
    };
    const root = byId.get(projection.root_region_id);
    if (!root) throw new Error('The Flow layout has no canonical root region.');
    measure(root);
    const boxes: WorkflowFlowBox[] = [];
    const place = (node: WorkflowInspectionNode, x: number, y: number) => {
        const size = sizes.get(node.id);
        if (!size) throw new Error('The Flow layout contains an unmeasured node.');
        const descendants = collapsed.has(node.id) ? [] : children.get(node.id) ?? [];
        boxes.push({
            id: node.id, ...(node.parent_id === null ? {} : { parentId: node.parent_id }),
            position: { x, y }, ...size, container: descendants.length > 0,
        });
        let offset = node.kind === 'if' ? PADDING : HEADER;
        for (const child of descendants) {
            const childSize = sizes.get(child.id);
            if (!childSize) throw new Error('The Flow layout contains an unmeasured region.');
            place(child, node.kind === 'if' ? offset : (size.width - childSize.width) / 2,
                node.kind === 'if' ? HEADER : offset);
            offset += (node.kind === 'if' ? childSize.width : childSize.height) + GAP;
        }
    };
    place(root, 0, 0);
    return boxes;
}

export function visibleWorkflowNode(
    nodeId: string,
    nodes: ReadonlyMap<string, WorkflowInspectionNode>,
    collapsed: ReadonlySet<string>,
): string {
    const node = nodes.get(nodeId);
    if (!node) throw new Error('The Flow relationship references an unavailable node.');
    let visibleId = nodeId;
    let parentId = node.parent_id;
    while (parentId !== null) {
        const parent = nodes.get(parentId);
        if (!parent) throw new Error('The Flow relationship has an unavailable parent.');
        if (collapsed.has(parentId)) visibleId = parentId;
        parentId = parent.parent_id;
    }
    return visibleId;
}

export function visibleWorkflowEdges(
    projection: WorkflowFlowProjection,
    collapsed: ReadonlySet<string>,
): WorkflowInspectionEdge[] {
    const nodes = new Map(projection.nodes.map((node) => [node.id, node]));
    const seen = new Set<string>();
    const edges: WorkflowInspectionEdge[] = [];
    for (const edge of projection.edges) {
        const source = visibleWorkflowNode(edge.source, nodes, collapsed);
        const target = visibleWorkflowNode(edge.target, nodes, collapsed);
        if (source === target) continue;
        const key = JSON.stringify([source, target, edge.kind, edge.label]);
        if (seen.has(key)) continue;
        seen.add(key);
        edges.push({ ...edge, source, target });
    }
    return edges;
}
