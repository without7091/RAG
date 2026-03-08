"use client";

import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  Database,
  Folder,
  Loader2,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type {
  KBFolderInfo,
  KBInfo,
  KBTreeKnowledgeBaseNode,
  KBTreeRootFolderNode,
} from "@/lib/api";

interface KBTreeProps {
  tree: KBTreeRootFolderNode[];
  selectedKb: string | null;
  selectedFolderId: string | null;
  copiedId: string | null;
  deletingFolderId: string | null;
  deletingKbId: string | null;
  expandedFolderIds: Set<string>;
  onToggleFolder: (folderId: string) => void;
  onSelectFolder: (folderId: string) => void;
  onSelectKb: (kbId: string) => void;
  onCreateChildFolder: (folder: KBFolderInfo) => void;
  onCreateKb: (folderId: string) => void;
  onEditFolder: (folder: KBFolderInfo) => void;
  onEditKb: (kb: KBInfo) => void;
  onDeleteFolder: (folderId: string) => void;
  onDeleteKb: (kbId: string) => void;
  onCopyKbId: (kbId: string) => void;
}

function toFolderInfo(folder: {
  folder_id: string;
  folder_name: string;
  parent_folder_id: string | null;
  depth: 1 | 2;
  created_at: string;
}): KBFolderInfo {
  return {
    folder_id: folder.folder_id,
    folder_name: folder.folder_name,
    parent_folder_id: folder.parent_folder_id,
    depth: folder.depth,
    created_at: folder.created_at,
  };
}

function toKbInfo(kb: KBTreeKnowledgeBaseNode): KBInfo {
  return {
    knowledge_base_id: kb.knowledge_base_id,
    knowledge_base_name: kb.knowledge_base_name,
    folder_id: kb.folder_id,
    folder_name: kb.folder_name,
    parent_folder_id: kb.parent_folder_id,
    parent_folder_name: kb.parent_folder_name,
    description: kb.description,
    document_count: kb.document_count,
    created_at: kb.created_at,
  };
}

export function KBTree({
  tree,
  selectedKb,
  selectedFolderId,
  copiedId,
  deletingFolderId,
  deletingKbId,
  expandedFolderIds,
  onToggleFolder,
  onSelectFolder,
  onSelectKb,
  onCreateChildFolder,
  onCreateKb,
  onEditFolder,
  onEditKb,
  onDeleteFolder,
  onDeleteKb,
  onCopyKbId,
}: KBTreeProps) {
  return (
    <div className="space-y-1">
      {tree.map((root) => {
        const rootExpanded = expandedFolderIds.has(root.folder_id);
        const rootSelected = selectedFolderId === root.folder_id;

        return (
          <div key={root.folder_id} className="space-y-1">
            <FolderRow
              expanded={rootExpanded}
              iconClassName={rootSelected ? "text-accent-foreground" : "text-primary"}
              meta={`${root.child_folder_count} 个子目录 · ${root.knowledge_base_count} 个知识集`}
              selected={rootSelected}
              title={root.folder_name}
              onSelect={() => onSelectFolder(root.folder_id)}
              onToggle={() => onToggleFolder(root.folder_id)}
              actions={
                <>
                  <ActionButton onClick={() => onCreateChildFolder(toFolderInfo(root))}>
                    <Plus className="h-3.5 w-3.5" />
                  </ActionButton>
                  <ActionButton onClick={() => onEditFolder(toFolderInfo(root))}>
                    <Pencil className="h-3.5 w-3.5" />
                  </ActionButton>
                  <ActionButton
                    disabled={deletingFolderId === root.folder_id}
                    onClick={() => onDeleteFolder(root.folder_id)}
                  >
                    {deletingFolderId === root.folder_id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Trash2 className="h-3.5 w-3.5" />
                    )}
                  </ActionButton>
                </>
              }
            />

            {rootExpanded && (
              <div className="space-y-1 pl-6">
                {root.children.map((child) => {
                  const childExpanded = expandedFolderIds.has(child.folder_id);
                  const childSelected = selectedFolderId === child.folder_id;

                  return (
                    <div key={child.folder_id} className="space-y-1">
                      <FolderRow
                        expanded={childExpanded}
                        iconClassName={
                          childSelected ? "text-accent-foreground" : "text-muted-foreground"
                        }
                        meta={`${child.knowledge_base_count} 个知识集`}
                        selected={childSelected}
                        title={child.folder_name}
                        onSelect={() => onSelectFolder(child.folder_id)}
                        onToggle={() => onToggleFolder(child.folder_id)}
                        actions={
                          <>
                            <ActionButton onClick={() => onCreateKb(child.folder_id)}>
                              <Plus className="h-3.5 w-3.5" />
                            </ActionButton>
                            <ActionButton onClick={() => onEditFolder(toFolderInfo(child))}>
                              <Pencil className="h-3.5 w-3.5" />
                            </ActionButton>
                            <ActionButton
                              disabled={deletingFolderId === child.folder_id}
                              onClick={() => onDeleteFolder(child.folder_id)}
                            >
                              {deletingFolderId === child.folder_id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <Trash2 className="h-3.5 w-3.5" />
                              )}
                            </ActionButton>
                          </>
                        }
                      />

                      {childExpanded && (
                        <div className="space-y-1 pl-6">
                          {child.knowledge_bases.length === 0 ? (
                            <p className="px-2 py-1 text-xs text-muted-foreground">
                              暂无知识集
                            </p>
                          ) : (
                            child.knowledge_bases.map((kb) => {
                              const isSelected = selectedKb === kb.knowledge_base_id;

                              return (
                                <div
                                  key={kb.knowledge_base_id}
                                  role="button"
                                  onClick={() => onSelectKb(kb.knowledge_base_id)}
                                  className={cn(
                                    "group flex cursor-pointer items-center justify-between rounded-md px-2 py-2 text-sm transition-colors",
                                    isSelected
                                      ? "bg-primary text-primary-foreground"
                                      : "hover:bg-accent"
                                  )}
                                >
                                  <div className="min-w-0 flex items-center gap-2">
                                    <Database className="h-4 w-4 shrink-0" />
                                    <div className="min-w-0">
                                      <div className="truncate font-medium">
                                        {kb.knowledge_base_name}
                                      </div>
                                      <div className="flex items-center gap-1">
                                        <span
                                          className={cn(
                                            "truncate text-xs font-mono",
                                            isSelected
                                              ? "text-primary-foreground/70"
                                              : "text-muted-foreground"
                                          )}
                                        >
                                          {kb.knowledge_base_id}
                                        </span>
                                        <button
                                          type="button"
                                          onClick={(event) => {
                                            event.stopPropagation();
                                            onCopyKbId(kb.knowledge_base_id);
                                          }}
                                          className={cn(
                                            "inline-flex h-4 w-4 shrink-0 items-center justify-center rounded",
                                            "opacity-0 transition-opacity group-hover:opacity-100",
                                            isSelected
                                              ? "text-primary-foreground/70 hover:bg-primary-foreground/20"
                                              : "text-muted-foreground hover:bg-accent-foreground/10"
                                          )}
                                        >
                                          {copiedId === kb.knowledge_base_id ? (
                                            <Check className="h-3 w-3" />
                                          ) : (
                                            <Copy className="h-3 w-3" />
                                          )}
                                        </button>
                                      </div>
                                      <div
                                        className={cn(
                                          "text-xs",
                                          isSelected
                                            ? "text-primary-foreground/70"
                                            : "text-muted-foreground"
                                        )}
                                      >
                                        {kb.document_count} 个文件
                                      </div>
                                    </div>
                                  </div>
                                  <div className="flex shrink-0 items-center gap-0.5">
                                    <ActionButton onClick={() => onEditKb(toKbInfo(kb))}>
                                      <Pencil className="h-3.5 w-3.5" />
                                    </ActionButton>
                                    <ActionButton
                                      disabled={deletingKbId === kb.knowledge_base_id}
                                      onClick={() => onDeleteKb(kb.knowledge_base_id)}
                                    >
                                      {deletingKbId === kb.knowledge_base_id ? (
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                      ) : (
                                        <Trash2 className="h-3.5 w-3.5" />
                                      )}
                                    </ActionButton>
                                  </div>
                                </div>
                              );
                            })
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function FolderRow({
  expanded,
  selected,
  title,
  meta,
  iconClassName,
  actions,
  onSelect,
  onToggle,
}: {
  expanded: boolean;
  selected: boolean;
  title: string;
  meta: string;
  iconClassName: string;
  actions: React.ReactNode;
  onSelect: () => void;
  onToggle: () => void;
}) {
  return (
    <div
      role="button"
      onClick={onSelect}
      className={cn(
        "group flex cursor-pointer items-center justify-between rounded-md px-2 py-2 text-sm transition-colors",
        selected ? "bg-accent text-accent-foreground" : "hover:bg-accent"
      )}
    >
      <div className="min-w-0 flex items-center gap-2">
        <ExpandButton expanded={expanded} onClick={onToggle} />
        <Folder className={cn("h-4 w-4", iconClassName)} />
        <div className="min-w-0">
          <div className="truncate font-medium">{title}</div>
          <div
            className={cn(
              "text-xs",
              selected ? "text-accent-foreground/70" : "text-muted-foreground"
            )}
          >
            {meta}
          </div>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-0.5">{actions}</div>
    </div>
  );
}

function ExpandButton({
  expanded,
  onClick,
}: {
  expanded: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
      className="inline-flex h-4 w-4 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:bg-accent-foreground/10"
    >
      {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
    </button>
  );
}

function ActionButton({
  children,
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      variant="ghost"
      size="sm"
      className="h-7 w-7 p-0 opacity-0 group-hover:opacity-100"
      disabled={disabled}
      onClick={(event) => {
        event.stopPropagation();
        onClick();
      }}
    >
      {children}
    </Button>
  );
}
