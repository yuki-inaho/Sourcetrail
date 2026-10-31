#include "SourceGroupCustomCommand.h"

#include "ExternalIndexerCommandBuilder.h"
#include "FileManager.h"
#include "FilePathFilter.h"
#include "RefreshInfo.h"
#include "SourceGroupSettingsCustomCommand.h"
#include "utility.h"

SourceGroupCustomCommand::SourceGroupCustomCommand(
	std::shared_ptr<SourceGroupSettingsCustomCommand> settings)
	: m_settings(settings)
{
}

bool SourceGroupCustomCommand::allowsPartialClearing() const
{
	return false;
}

std::set<FilePath> SourceGroupCustomCommand::filterToContainedFilePaths(
	const std::set<FilePath>& filePaths) const
{
	return SourceGroup::filterToContainedFilePaths(
		filePaths,
		std::set<FilePath>(),
		utility::toSet(m_settings->getSourcePathsExpandedAndAbsolute()),
		m_settings->getExcludeFiltersExpandedAndAbsolute());
}

std::set<FilePath> SourceGroupCustomCommand::getAllSourceFilePaths() const
{
	FileManager fileManager;
	fileManager.update(
		m_settings->getSourcePathsExpandedAndAbsolute(),
		m_settings->getExcludeFiltersExpandedAndAbsolute(),
		m_settings->getSourceExtensions());
	std::set<FilePath> paths = fileManager.getAllSourceFilePaths();
	if (m_settings->getType() == SOURCE_GROUP_MODERN)
	{
		// Explicit manifests and adapter configurations are observed inputs even
		// when their extensions differ from the language's source extensions.
		for (const FilePath& path: m_settings->getSourcePathsExpandedAndAbsolute())
		{
			if (path.exists() && !path.isDirectory())
			{
				paths.insert(path);
			}
		}
	}
	return paths;
}

std::vector<std::shared_ptr<IndexerCommand>> SourceGroupCustomCommand::getIndexerCommands(
	const RefreshInfo& info) const
{
	if (m_settings->getType() == SOURCE_GROUP_MODERN)
	{
		// Whole-project semantic engines share one Cargo/CDB/import context. The
		// group disallows partial clearing; schedule exactly one serial command.
		const std::set<FilePath> paths = getAllSourceFilePaths();
		for (const FilePath& path: paths)
		{
			if (info.filesToIndex.find(path) != info.filesToIndex.end())
			{
				return createExternalIndexerCommands(
					{INDEXER_COMMAND_CUSTOM, m_settings->getCustomCommand(), {}, false},
					m_settings->getProjectSettings(), {path}, {path});
			}
		}
		return {};
	}
	return createExternalIndexerCommands(
		{INDEXER_COMMAND_CUSTOM, m_settings->getCustomCommand(), {}, m_settings->getRunInParallel()},
		m_settings->getProjectSettings(),
		getAllSourceFilePaths(),
		info.filesToIndex);
}

std::shared_ptr<SourceGroupSettings> SourceGroupCustomCommand::getSourceGroupSettings()
{
	return m_settings;
}

std::shared_ptr<const SourceGroupSettings> SourceGroupCustomCommand::getSourceGroupSettings() const
{
	return m_settings;
}
