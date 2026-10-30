#include "RefreshPlan.h"

#include <utility>

#include "RefreshPlanner.h"

RefreshPlan RefreshPlan::forUpdatedFiles(
	const FilePaths& allSourceFiles,
	const FilePaths& unchangedIndexedFiles,
	const FilePaths& changedFiles,
	const DependencyQuery& referenced,
	const DependencyQuery& referencing)
{
	// Keep the storage query sequence explicit: C++ argument evaluation order must not
	// choose which snapshot observation occurs first. The portable core sees values only.
	const FilePaths dependentFiles = referencing(changedFiles);
	const auto selection = sourcetrail::core::prepareUpdatedRefresh(
		allSourceFiles, changedFiles, dependentFiles);
	const FilePaths staticReferencedFiles = referenced(selection.staticSourceFiles);
	const FilePaths dynamicReferencedFiles = referenced(selection.initialFilesToClear);
	auto result = sourcetrail::core::finishUpdatedRefresh(
		allSourceFiles,
		unchangedIndexedFiles,
		selection,
		staticReferencedFiles,
		dynamicReferencedFiles);
	return RefreshPlan {std::move(result.filesToClear), std::move(result.filesToIndex)};
}
