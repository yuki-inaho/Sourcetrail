#ifndef SOURCETRAIL_CORE_SOURCE_CHANGE_H
#define SOURCETRAIL_CORE_SOURCE_CHANGE_H

#include <string>

namespace sourcetrail
{
namespace core
{

// Missing and NULL storage rows are not successful observations of an empty file.
enum class SourceContentStatus
{
	Available,
	Missing,
	Null,
	ReadError
};

struct SourceContent
{
	SourceContentStatus status = SourceContentStatus::Missing;
	std::string text;
};

// INPUT-001: content is authoritative whenever both observations are available.
// The timestamp fallback is retained only for unindexed dependencies without a
// stored content row. IO, timestamps and the refresh graph stay in the adapter.
inline bool didSourceChange(
	bool indexed,
	const SourceContent& stored,
	const SourceContent& current,
	bool currentTimestampIsNewer)
{
	if (current.status != SourceContentStatus::Available)
	{
		return true;
	}
	if (stored.status == SourceContentStatus::Available)
	{
		return stored.text != current.text;
	}
	if (!indexed && stored.status == SourceContentStatus::Missing)
	{
		return currentTimestampIsNewer;
	}
	return true;
}

} // namespace core
} // namespace sourcetrail

#endif // SOURCETRAIL_CORE_SOURCE_CHANGE_H
