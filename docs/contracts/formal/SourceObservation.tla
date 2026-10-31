------------------------- MODULE SourceObservation -------------------------
EXTENDS Naturals

CONSTANT TimestampGate
VARIABLES indexed, storedStatus, currentStatus, stored, current, newer, phase, changed
vars == <<indexed, storedStatus, currentStatus, stored, current, newer, phase, changed>>
Statuses == {"available", "missing", "null", "read-error"}
Contents == {"", "a", "b"}

Init ==
    /\ indexed \in BOOLEAN
    /\ storedStatus \in Statuses
    /\ currentStatus \in Statuses
    /\ stored \in Contents
    /\ current \in Contents
    /\ newer \in BOOLEAN
    /\ phase = "observed"
    /\ changed = FALSE

Classify ==
    /\ phase = "observed"
    /\ changed' = IF currentStatus # "available" THEN TRUE
                   ELSE IF storedStatus = "available"
                        THEN (stored # current) /\ (~TimestampGate \/ newer)
                   ELSE IF ~indexed /\ storedStatus = "missing" THEN newer
                   ELSE TRUE
    /\ phase' = "classified"
    /\ UNCHANGED <<indexed, storedStatus, currentStatus, stored, current, newer>>

Finish == /\ phase = "classified" /\ UNCHANGED vars
Spec == Init /\ [][Classify \/ Finish]_vars

TypeInvariant ==
    /\ indexed \in BOOLEAN
    /\ storedStatus \in Statuses
    /\ currentStatus \in Statuses
    /\ stored \in Contents
    /\ current \in Contents
    /\ newer \in BOOLEAN
    /\ changed \in BOOLEAN
    /\ phase \in {"observed", "classified"}

ContentChangesDetected ==
    phase = "classified" /\ storedStatus = "available" /\ currentStatus = "available"
    /\ stored # current => changed
EqualContentIgnoresTimestamp ==
    phase = "classified" /\ storedStatus = "available" /\ currentStatus = "available"
    /\ stored = current => ~changed
UnavailableInputIsConservative ==
    phase = "classified" /\ currentStatus # "available" => changed
MissingIndexedContentIsConservative ==
    phase = "classified" /\ indexed /\ storedStatus # "available" => changed
UnindexedFallbackIsExplicit ==
    phase = "classified" /\ ~indexed /\ storedStatus = "missing"
    /\ currentStatus = "available" => changed = newer
=============================================================================
