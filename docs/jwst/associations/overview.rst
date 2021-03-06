.. _asn-overview:

====================
Association Overview
====================

.. _asn-what-are-associations:

What are Associations?
======================

Associations are basically just lists of things, mostly exposures,
that are somehow related. With respect to JWST and the Data Management
System (DMS), associations have the following characteristics:

- Relationships between multiple exposures are captured in an association.
- An association is a means of identifying a set of exposures that belong together and may be dependent upon one another.
- The association concept permits exposures to be calibrated, archived, retrieved, and reprocessed as a set rather than as individual objects.
- For each association, DMS will generate the most combined and least combined data products.

.. _asn-associations-and-jwst:

Associations and JWST
=====================

The basic chunk in which science data arrives from the observatory is
termed an `exposure`. An exposure contains the data from a single set
of integrations per detector per instrument. In general, it takes many
exposures to make up a single observation, and a whole program is made
up of a large number of observations.

On first arrival, an exposure is termed to be at `Level1b`: The only
transformation that has occured is the extraction of the science data
from the observatory telemetry into a FITS file. At this point, the
science exposures enter the calibration pipeline.

The pipeline consists of two stages: Level2 processing and Level3
processing. Level2 processing is the calibration necessary to remove
instrumental effects from the data. The resulting files contain flux
and spatially calibrated data, called `Level2b` data. The information
is still in individual exposures.

To be truly useful, the exposures need to be combined and, in the case
of multi-object spectrometry, separated, into data that is
source-oriented. This type of calibration is called `Level3`
processing. Due to the nature of the individual instruments, observing
modes, and the interruptability of the observatory itself, how to
group the right exposures together is not straight-forward.

Enter the :ref:`Association Generator <association-generator>`. Given a set of exposures,
called the :ref:`Association Pool <asn-pool>`, and a set of rules found in an
:ref:`Association Registry <asn-registry>`, the generator groups the exposures into
individual :ref:`associations <association>`. These associations are
then used as input to the Level3 calibration steps to perform the
transformation from exposure-based data to source-based, high(er)
signal-to-noise data.

In short, Level 2 and Level 3 associations are created running the
:ref:`asn_generate <asn-generate>` task on an :ref:`Association Pool
<asn-pool>` using the default :ref:`Level 2` and :ref:`Level 3
Association Rules <level3-asn-rules>` to produce
:ref:`level2-associations` and :ref:`level3-associations`.

.. _asn-usage:

Usage
=====

Users should not need to run the generator. Instead, it is expected
that one edits an already existing association that accompanies the
user's JWST data. Or, if need be, an association can be created based
on the existing :ref:`Level2 <asn-level2-example>` or
:ref:`Level3 <asn-level3-example>` examples.

Once an association is in-hand, one can pass it as input to a pipeline
routine. For example::

  % strun calwebb_image3.cfg  jw12345_xxxx_asn.json

Programmatically, to read in an Association, one uses the
:func:`~jwst.associations.load_asn.load_asn` function:

.. code-block:: python

   from jwst.associations import load_asn

   with open('jw12345_xxxx_asn.json') as fp:
       asn = load_asn(fp)

What exactly is returned depends on what the association is. However,
for all Level2 and Level3 associations, a Python `dict` is returned,
whose structure matches that of the `JSON` or `YAML` file. Continuing
from the above example, the following shows how to access the first
exposure file name of a Level3 assocations::

  exposure = asn['products'][0]['members'][0]['expname']

Since the JWST pipeline uses associations extensively, higher-level
access is gained by opening an association as a :ref:`JWST Data
Model`:

.. code-block:: python

  from jwst.datamodels import open as dm_open
  container_model = dm_open('jw12345_xxxx_asn.json')

.. _asn-utilities:

Utilities
=========

Other useful utilities for creating and manipulating associations:

- `asn_from_list`
- *many other TBD*
