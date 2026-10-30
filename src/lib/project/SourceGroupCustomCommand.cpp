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
	return fileManager.getAllSourceFilePaths();
}

std::vector<std::shared_ptr<IndexerCommand>> SourceGroupCustomCommand::getIndexerCommands(
	const RefreshInfo& info) const
{
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
