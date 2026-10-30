#ifndef REFRESH_PLAN_H
#define REFRESH_PLAN_H

#include <functional>
#include <set>

#include "FilePath.h"

// FilePath/storage-query adapter for the value-only sourcetrail::core refresh planner.
// File discovery, change detection, storage writes, and the indexed/non-indexed partition
// remain in RefreshInfoGenerator. Keep this API for existing application callers.
struct RefreshPlan
{
	using FilePaths = std::set<FilePath>;
	using DependencyQuery = std::function<FilePaths(const FilePaths&)>;

	// REFRESH-001: Return the legacy updated-refresh plan for one fixed dependency snapshot.
	// Both queries must be deterministic, read-only transitive dependency queries. The storage
	// adapter currently unions include and import closures separately; do not join those
	// relations here. Paths are already normalized by the caller and are never inspected on disk.
	// REFRESH-002: Keep dependencies still needed by unaffected source files out of cleanup,
	// unless the dependency is itself changed or references a changed file.
	static RefreshPlan forUpdatedFiles(
		const FilePaths& allSourceFiles,
		const FilePaths& unchangedIndexedFiles,
		const FilePaths& changedFiles,
		const DependencyQuery& referenced,
		const DependencyQuery& referencing);

	FilePaths filesToClear;
	FilePaths filesToIndex;
};

#endif	  // REFRESH_PLAN_H
