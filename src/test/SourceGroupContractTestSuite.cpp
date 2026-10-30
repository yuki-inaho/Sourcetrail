#include "catch.hpp"

#include <algorithm>
#include <utility>

#include <QTemporaryDir>

#include "FilePath.h"
#include "FilePathFilter.h"
#include "SourceGroup.h"

namespace
{
using Paths = std::set<FilePath>;

class ContractSourceGroup: public SourceGroup
{
public:
	explicit ContractSourceGroup(Paths sourceFiles): m_sourceFiles(std::move(sourceFiles)) {}

	Paths getAllSourceFilePaths() const override
	{
		return m_sourceFiles;
	}

	Paths filterToContainedFilePaths(const Paths& filePaths) const override
	{
		Paths contained;
		for (const FilePath& path: filePaths)
		{
			if (m_sourceFiles.find(path) != m_sourceFiles.end())
			{
				contained.insert(path);
			}
		}
		return contained;
	}

	std::vector<std::shared_ptr<IndexerCommand>> getIndexerCommands(const RefreshInfo&) const override
	{
		return {};
	}

	Paths configuredFilePaths(
		const Paths& candidates,
		const Paths& configuredPaths,
		const std::vector<FilePathFilter>& exclusions = {}) const
	{
		return SourceGroup::filterToContainedFilePaths(candidates, {}, configuredPaths, exclusions);
	}

protected:
	std::shared_ptr<SourceGroupSettings> getSourceGroupSettings() override
	{
		return nullptr;
	}

	std::shared_ptr<const SourceGroupSettings> getSourceGroupSettings() const override
	{
		return nullptr;
	}

private:
	Paths m_sourceFiles;
};

bool samePaths(const Paths& left, const Paths& right)
{
	// Match std::set identity; FilePath::operator== can consult the filesystem.
	return left.size() == right.size() &&
		std::equal(left.begin(), left.end(), right.begin(), [](const FilePath& a, const FilePath& b) {
			   return !(a < b) && !(b < a);
		   });
}
}	 // namespace

TEST_CASE("source group contract handles an empty source set", "[contract][source-group]")
{
	const ContractSourceGroup group({});
	const FilePath path(L"source.cpp");
	REQUIRE_FALSE(group.containsSourceFilePath(path));
	REQUIRE(group.getSourceFilePathsExcept({}).empty());
	REQUIRE(group.getSourceFilePathsExcept({path}).empty());
}

TEST_CASE("source group contract recognizes a singleton member", "[contract][source-group]")
{
	// SOURCE-GROUP-001: the former complement/nonempty predicate rejected this member.
	const FilePath source(L"source.cpp");
	const FilePath other(L"other.cpp");
	const ContractSourceGroup group({source});
	REQUIRE(group.containsSourceFilePath(source));
	REQUIRE_FALSE(group.containsSourceFilePath(other));
}

TEST_CASE(
	"source group contract rejects nonmembers of a multiple source set", "[contract][source-group]")
{
	const FilePath first(L"first.cpp");
	const FilePath second(L"second.cpp");
	const ContractSourceGroup group({first, second});
	REQUIRE(group.containsSourceFilePath(first));
	REQUIRE(group.containsSourceFilePath(second));
	REQUIRE_FALSE(group.containsSourceFilePath(FilePath(L"unrelated.cpp")));
}

TEST_CASE(
	"source group contract subtracts exclusions without mutating the group",
	"[contract][source-group]")
{
	const FilePath first(L"first.cpp");
	const FilePath second(L"second.cpp");
	const FilePath other(L"unrelated.cpp");
	const ContractSourceGroup group({first, second});
	REQUIRE(samePaths(group.getSourceFilePathsExcept({}), {first, second}));
	REQUIRE(samePaths(group.getSourceFilePathsExcept({first}), {second}));
	REQUIRE(samePaths(group.getSourceFilePathsExcept({second}), {first}));
	REQUIRE(samePaths(group.getSourceFilePathsExcept({other}), {first, second}));
	REQUIRE(group.getSourceFilePathsExcept({first, second, other}).empty());
	REQUIRE(samePaths(group.getAllSourceFilePaths(), {first, second}));
}

TEST_CASE(
	"source group contract preserves the historical exclusion alias", "[contract][source-group]")
{
	const FilePath first(L"first.cpp");
	const FilePath second(L"second.cpp");
	const FilePath other(L"unrelated.cpp");
	const ContractSourceGroup group({first, second});
	for (const Paths& excluded: std::vector<Paths> {{}, {first}, {second}, {other}, {first, second}})
	{
		REQUIRE(samePaths(
			group.filterToContainedSourceFilePath(excluded),
			group.getSourceFilePathsExcept(excluded)));
	}
}

TEST_CASE(
	"source group contract owns removed files beneath configured roots", "[contract][source-group]")
{
	QTemporaryDir directory;
	REQUIRE(directory.isValid());
	const FilePath root(directory.path().toStdWString());
	const FilePath removed = root.getConcatenated(L"removed.py");
	const FilePath neighbour(root.wstr() + L"-other/removed.py");
	const ContractSourceGroup group({});
	REQUIRE_FALSE(group.containsSourceFilePath(removed));
	REQUIRE(samePaths(group.configuredFilePaths({removed, neighbour}, {root}), {removed}));
	REQUIRE(group.configuredFilePaths({removed}, {root}, {FilePathFilter(removed.wstr())}).empty());
}

TEST_CASE(
	"source group contract owns an explicitly configured removed file", "[contract][source-group]")
{
	QTemporaryDir directory;
	REQUIRE(directory.isValid());
	const FilePath removed(directory.path().toStdWString() + L"/removed.py");
	const FilePath other(directory.path().toStdWString() + L"/other.py");
	const ContractSourceGroup group({});
	REQUIRE_FALSE(group.containsSourceFilePath(removed));
	REQUIRE(samePaths(group.configuredFilePaths({removed, other}, {removed}), {removed}));
}
