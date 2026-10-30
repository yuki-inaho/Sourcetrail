#ifndef EXTERNAL_INDEXER_COMMAND_BUILDER_H
#define EXTERNAL_INDEXER_COMMAND_BUILDER_H

#include <memory>
#include <set>
#include <string>
#include <vector>

#include "FilePath.h"
#include "IndexerCommandType.h"

class IndexerCommand;
class ProjectSettings;

// Language adapters specify their executable and arguments; this common adapter
// owns selection, project/database context, ordering and command construction.
// projectSettings is required only when at least one source is selected, preserving
// the existing empty-group behavior during project setup.
struct ExternalIndexerCommandSpec
{
	IndexerCommandType type;
	std::wstring command;
	std::vector<std::wstring> arguments;
	bool runInParallel;
};

std::vector<std::shared_ptr<IndexerCommand>> createExternalIndexerCommands(
	const ExternalIndexerCommandSpec& specification,
	const ProjectSettings* projectSettings,
	const std::set<FilePath>& sourceFiles,
	const std::set<FilePath>& filesToIndex);

#endif
