from __future__ import division

import logging

import numpy as np
from scipy.ndimage.filters import convolve1d
from .. import datamodels

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

def correct_model(input_model, irs2_model,
                  scipix_n_default=16, refpix_r_default=4, pad=8):
    """Process IRS^2 data.

    Parameters
    ----------
    input_model: ramp model
        The input science data model.

    irs2_model: IRS^2 model
        The reference file model for IRS^2 correction.

    scipix_n_default: int
        Number of regular samples before stepping out to collect
        reference samples.

    refpix_r_default: int
        Number of reference samples before stepping back in to collect
        regular samples.

    pad: int
        The effective number of pixels sampled during the pause at the end
        of each row (new-row overhead).  The padding is needed to preserve
        the phase of temporally periodic signals.

    Returns
    -------
    output_model: ramp model
        The science data with reference output and reference pixels
        subtracted.
    """


    #; Part_C applies the calibration as derived from part_A and part_B.

    """Readout parameters
    scipix_n   16         Number of regular samples before stepping out
                          to collect reference samples
    refpix_r    4         Number of reference samples before stepping back
                          in to collect regular samples
    NFOH        1 row     New frame overhead (714?)
    NROH        8 pixels  New row overhead (`pad`)
    JOH         1 pixel   Jump overhead for stepping out to or in from
                          reference pixels
    TPIX       10 microseconds  Pixel dwell time
    tframe     14.5889 s  Frame readout time

    The image and reference data will be rearranged into a 1-D array
    containing the values in time order, i.e. the element number * TPIX
    is the relative time at which a pixel was read out.  This array will
    have elements corresponding to the gaps (overheads) when no pixel was
    being read.  This 1-D array has length 1,458,176, which is equal to
    712 * 2048:

    ((scipix_n + refpix_r + 2) * (512 // scipix_n) + NROH) * 2048

    The total frame readout time is:
    (((scipix_n + refpix_r + 2) * (512 // scipix_n) + NROH) * 2048 + NFOH)
        * TPIX
    This agrees with the above value of tframe (14.5889 s) if NFOH = 714.
    """

    output_model = input_model.copy()
    output_model.meta.cal_step.refpix = 'not specified yet'

    # Get reference data.
    # The reference data are complex, but they're stored as float, with
    # alternating real and imaginary parts.  We therefore check for twice
    # as many rows as we actually want, and we'll divide that number by two
    # when allocating the arrays alpha and beta.
    nrows = len(irs2_model.irs2_table.field("alpha_0"))
    expected_nrows = 2 * 712 * 2048
    if nrows != expected_nrows:
        log.error("Number of rows in reference file = {},"
                  " but it should be {}.".format(nrows, expected_nrows))
        output_model.meta.cal_step.refpix = 'SKIPPED'
        return output_model
    alpha = np.ones((4, nrows // 2), dtype=np.complex64)
    beta = np.zeros((4, nrows // 2), dtype=np.complex64)

    alpha[0, :] = float_to_complex(
                        irs2_model.irs2_table.field("alpha_0"))
    alpha[1, :] = float_to_complex(
                        irs2_model.irs2_table.field("alpha_1"))
    alpha[2, :] = float_to_complex(
                        irs2_model.irs2_table.field("alpha_2"))
    alpha[3, :] = float_to_complex(
                        irs2_model.irs2_table.field("alpha_3"))

    beta[0, :] = float_to_complex(
                    irs2_model.irs2_table.field("beta_0"))
    beta[1, :] = float_to_complex(
                    irs2_model.irs2_table.field("beta_1"))
    beta[2, :] = float_to_complex(
                    irs2_model.irs2_table.field("beta_2"))
    beta[3, :] = float_to_complex(
                    irs2_model.irs2_table.field("beta_3"))

    if beta is None:
        log.info("Using reference pixels only.")

    scipix_n = input_model.meta.exposure.nrs_normal
    if scipix_n is None:
        log.warning("Keyword NRS_NORM not found; using default value %d" %
                    scipix_n_default)
        scipix_n = scipix_n_default

    refpix_r = input_model.meta.exposure.nrs_reference
    if refpix_r is None:
        log.warning("Keyword NRS_REF not found; using default value %d" %
                    refpix_r_default)
        refpix_r = refpix_r_default

    data = output_model.data
    detector = input_model.meta.instrument.detector
    # Convert from sky (DMS) orientation to detector orientation.
    if detector == "NRS1":
        data = np.swapaxes(data, 2, 3)
    elif detector == "NRS2":
        data = np.swapaxes(data, 2, 3)[:, :, ::-1, ::-1]
    else:
        log.warning("Detector '%s'; not changing orientation (sky vs detector)"
                    % detector)

    n_int = data.shape[0]               # number of integrations in file
    ny = data.shape[-2]                 # 2048
    nx = data.shape[-1]                 # 3200

    # Boolean mask, True flags normal pixels (as opposed to reference output
    # or interspersed reference pixels).
    irs2_mask = make_irs2_mask(output_model, scipix_n, refpix_r)

    for integ in range(n_int):
        # The input data have a length of 3200 for the last axis (X), while
        # the output data have an X axis with length 2048, the same as the
        # Y axis.  This is the reason for the slice `nx-ny:` that is used
        # below.  The last axis of output_model.data should be 2048.
        data0 = data[integ, :, :, :]
        data0 = subtract_reference(data0, alpha, beta, irs2_mask,
                                   scipix_n, refpix_r, pad)
        data[integ, :, :, nx - ny:] = data0
    temp_data = data[:, :, :, nx - ny:]
    del data
    # Convert back to sky orientation.
    if detector == "NRS1":
        output_model.data = np.swapaxes(temp_data, 2, 3)
    elif detector == "NRS2":
        output_model.data = np.swapaxes(temp_data[:, :, ::-1, ::-1], 2, 3)
    else:                       # don't change orientation
        output_model.data = temp_data

    # Copy out the normal pixels of the PIXELDQ, GROUPDQ, and ERR extensions.
    exclude_ref(output_model, irs2_mask)

    return output_model


def float_to_complex(data):
    """Convert real and imaginary parts to complex"""

    nelem = len(data)

    return data[0:-1:2] + 1j * data[1:nelem:2]

def make_irs2_mask(output_model, scipix_n, refpix_r):

    # Number of (scipix_n + refpix_r) per output, assuming four amplifier
    # outputs and one reference output.
    shape = output_model.pixeldq.shape
    irs2_nx = max(shape)
    # Length of the reference output section.
    refout = irs2_nx // 5
    part = refout - (scipix_n // 2 + refpix_r)
    k = part // (scipix_n + refpix_r)
    # `part` consists of k * (scipix_n + refpix_r) + stuff_at_end
    stuff_at_end = part - k * (scipix_n + refpix_r)

    # Create the mask which flags normal pixels as True.
    irs2_mask = np.ones(irs2_nx, dtype=np.bool)
    irs2_mask[0:refout] = False

    # Check whether the interspersed reference pixels are in the same
    # locations regardless of readout direction.
    if stuff_at_end == scipix_n // 2:
        # Yes, they are in the same locations.
        for i in range(refout + scipix_n // 2, irs2_nx + 1,
                       scipix_n + refpix_r):
            irs2_mask[i:i + refpix_r] = False
    else:
        # Set the flags for each readout direction separately.
        nelem = refout                  # number of elements per output
        temp = np.ones(nelem, dtype=np.bool)
        for i in range(scipix_n // 2, nelem + 1,
                       scipix_n + refpix_r):
            temp[i:i + refpix_r] = False
        j = refout
        irs2_mask[j:j + nelem] = temp.copy()
        j += nelem
        irs2_mask[j:j + nelem] = temp[::-1].copy()
        j += nelem
        irs2_mask[j:j + nelem] = temp.copy()
        j += nelem
        irs2_mask[j:j + nelem] = temp[::-1].copy()

    return irs2_mask

def exclude_ref(output_model, irs2_mask):
    """Copy out the normal pixels from PIXELDQ, GROUPDQ, and ERR arrays.

    Parameters
    ----------
    output_model: ramp model
        The output science data model, to be modified in-place

    irs2_mask: Boolean, 1-D array of length 3200
        True means the element corresponds to a normal pixel in the raw,
        IRS2-format data.  False corresponds either to a reference output
        pixel or to one of the interspersed reference pixel values.
    """

    detector = output_model.meta.instrument.detector

    if detector == "NRS1":
        # Select rows.
        temp_array = output_model.pixeldq
        output_model.pixeldq = temp_array[..., irs2_mask, :]

        temp_array = output_model.groupdq
        output_model.groupdq = temp_array[..., irs2_mask, :]

        temp_array = output_model.err
        output_model.err = temp_array[..., irs2_mask, :]
    elif detector == "NRS2":
        # Reverse the direction of the mask, and select rows.
        temp_mask = irs2_mask[::-1]

        temp_array = output_model.pixeldq
        output_model.pixeldq = temp_array[..., temp_mask, :]

        temp_array = output_model.groupdq
        output_model.groupdq = temp_array[..., temp_mask, :]

        temp_array = output_model.err
        output_model.err = temp_array[..., temp_mask, :]
    else:
        # Select columns.
        temp_array = output_model.pixeldq
        output_model.pixeldq = temp_array[..., irs2_mask]

        temp_array = output_model.groupdq
        output_model.groupdq = temp_array[..., irs2_mask]

        temp_array = output_model.err
        output_model.err = temp_array[..., irs2_mask]

def subtract_reference(data0, alpha, beta, irs2_mask,
                       scipix_n, refpix_r, pad):
    """Subtract reference output and pixels for the current integration.

    Parameters
    ----------
    data0: ramp data
        The science data for the current integration.  The shape is
        expected to be (ngroups, ny, 3200), where ngroups is the number of
        groups, and ny is the pixel height of the image.  The width 3200
        of the image includes the "normal" pixel data, plus the embedded
        reference pixels, and the reference output.

    alpha: ndarray
        This is a 2-D array of values read from the reference file.  The
        first axis is the sector number (but only for the normal pixel
        data and reference pixels, not the reference output).  The second
        axis has length 2048 * 712, corresponding to the time-ordered
        arrangement of the data.  For each sector, the correction is
        applied as follows:  data * alpha[i] + reference_output * beta[i].

    beta: ndarray
        Data read from the reference file.  See `alpha` for details.

    irs2_mask: Boolean, 1-D array
        True means the element corresponds to a normal pixel in the raw,
        IRS2-format data.  False corresponds either to a reference output
        pixel or to one of the interspersed reference pixel values.

    scipix_n: int
        Number of regular samples before stepping out to collect
        reference samples.

    refpix_r: int
        Number of reference samples before stepping back in to collect
        regular samples.

    pad: int
        The effective number of pixels sampled during the pause at the end
        of each row (new-row overhead).

    Returns
    -------
    data0: ramp data
        The science data for the current integration, with reference output
        and embedded reference pixels subtracted and also removed, leaving
        only the normal pixel data (including the reference pixels on each
        edge).  The shape is expected to be (ngroups, ny, nx), where
        nx = ny = 2048.
    """

    shape = data0.shape
    ngroups = shape[0]
    ny = shape[1]
    nx = shape[2]

    # See expression in equation 1 in IRS2_Handoff.pdf.
    # row = 712, if scipix_n = 16, refpix_r = 4, pad = 8.
    row = (scipix_n + refpix_r + 2) * 512 // scipix_n + pad

    # s = size(data0)
    # If data0 is the data for one integration, then:
    # s[0] would be 3
    # s[1] = shape[2] = nx, the length of the X axis
    # s[2] = shape[1] = ny, the length of the Y axis
    # s[3] = shape[0] = ngroups, the number of groups (or frames)

    ind_n = np.arange(512, dtype=np.intp)
    ind_ref = np.arange(512 // scipix_n * refpix_r, dtype=np.intp)

    # hnorm is an array of column indices of normal pixels.
    # len(hnorm) = 512; len(href) = 128
    # len(hnorm1) = 512; len(href1) = 128
    hnorm = ind_n + refpix_r * ((ind_n + scipix_n // 2) // scipix_n)

    # href is an array of column indices of reference pixels.
    href = ind_ref + scipix_n * (ind_ref // refpix_r) + scipix_n // 2

    hnorm1 = ind_n + (refpix_r + 2) * ((ind_n + scipix_n // 2) // scipix_n)
    href1 = ind_ref + (scipix_n + 2) * (ind_ref // refpix_r) + \
            scipix_n // 2 + 1

    # Subtract the average over the ramp for each pixel.
    b_offset = data0.sum(axis=0, dtype=np.float64) / float(ngroups)
    data0 -= b_offset
    # Save b_offset, and add it back in at the end.

    # IDL:  data0 = reform(data0, s[1]/5, 5, s[2], s[3], /over)
    #                             nx/5,   5, ny,   ngroups    (IDL)
    data0 = data0.reshape((ngroups, ny, 5, nx // 5))

    # current order:  nx/5, 5, ny, ngroups    (IDL)
    # current order:  ngroups, ny, 5, nx/5    (numpy)
    #                 0        1   2  3       current numpy indices
    # transpose to:   nx/5, ny, ngroups, 5    (IDL)
    # transpose to:   5, ngroups, ny, nx/5    (numpy)
    #                 2  0        1   3       transpose order for numpy
    # Therefore:      0 1 2 3  -->  2 0 1 3   transpose order for numpy
    # Here is another way to look at it:
    # IDL:    0 1 2 3  -->  0 2 3 1
    #         3 2 1 0       1 3 2 0 (IDL indices, but reversed to numpy order)
    # numpy:  0 1 2 3  -->  2 0 1 3
    # IDL:  data0 = transpose(data0, [0,2,3,1])
    data0 = np.transpose(data0, (2, 0, 1, 3))

    # Flip the direction of the X axis for every other output, so the readout
    # direction in data0 will be the same for every output.
    data0[0, :, :, :] = data0[0, :, :, ::-1]
    data0[2, :, :, :] = data0[2, :, :, ::-1]
    data0[4, :, :, :] = data0[4, :, :, ::-1]

    # convert to time sequences of normal pixels and reference pixels.
    # IDL:  d0 = fltarr(s[1] / 5 + pad + 2 * (512 / scipix_n), s[2], s[3], 5)
    # Note:  nx // 5 + pad + 2 * (512 // scipix_n) = 640 + 64 + 8 = 712.
    # hnorm1[-1] = 703, and hnorm[-1] = 639, so 703 - 639 = 64.
    # 8 is the pad value.

    # d0.shape will be (5, ngroups, 2048, 712)
    d0 = np.zeros((5, ngroups, ny, row), dtype=np.float32)
    # IDL:  d0[hnorm1,*,*,*] = data0[hnorm,*,*,*]
    # IDL:  d0[href1,*,*,*] = data0[href,*,*,*]
    # IDL:  data0 = temporary(d0)
    d0[:, :, :, hnorm1] = data0[:, :, :, hnorm]
    d0[:, :, :, href1] = data0[:, :, :, href]
    data0 = d0.copy()
    del d0

    #; <<<<< Fitting and removal of slopes per frame to remove issues at frame
    # boundaries.
    # IDL:  time = findgen(row, s[2])
    time_arr = np.arange(ny * row, dtype=np.float32).reshape((ny, row))
    time_arr -= time_arr.mean(dtype=np.float64)
    row4plus4 = np.array([0, 1, 2, 3, 2044, 2045, 2046, 2047], dtype=np.intp)

    # For ab_3, it should be OK to use the same index order as the IDL code.
    ab_3 = np.zeros((2, ngroups, 5), dtype=np.float32)
    for i in range(5):
        for k in range(ngroups):
            # mask is 2-D, since both row4plus4 and : have more than one
            # element.
            mask = (data0[i, k, row4plus4, :] != 0.)
            (intercept, slope) = ols_line(time_arr[row4plus4, :][mask],
                                          data0[i, k, row4plus4, :][mask])
            ab_3[0, k, i] = intercept
            ab_3[1, k, i] = slope
    for i in range(5):
        for k in range(ngroups):
            # weight is 0 where data0 is 0, else 1.
            weight = (data0[i, k, :, :] != 0.).astype(np.float32)
            data0[i, k, :, :] -= (ab_3[0, k, i] +
                                  time_arr * ab_3[1, k, i]) * weight

    # <<<<<<<

    # ; Use cosine weighted interpolation to replace 0.0 values and bad
    # pixels and gaps. (initial guess)

    # s[1] = nx  s[2] = ny  s[3] = ngroups
    w_ind = np.arange(1, 32, dtype=np.float32) / 32.
    w = np.sin(w_ind * np.pi)
    kk = 0
    for jj in range(ngroups):
        dat = data0[kk, jj, :, :].reshape(row * ny)
        mask = (dat != 0.).astype(np.float32)
        numerator = convolve1d(dat, w, mode='wrap')
        denominator = convolve1d(mask, w, mode='wrap')
        div_zero = (denominator == 0.)          # check for divide by zero
        numerator = np.where(div_zero, 0., numerator)
        denominator = np.where(div_zero, 1., denominator)
        dat = numerator / denominator
        dat = dat.reshape(ny, row)
        mask = mask.reshape(ny, row)
        # xxx why '+=' instead of just '=' ?
        data0[kk, jj, :, :] += dat * (1. - mask)

    #;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
    # Use Fourier filter/interpolation to replace
    # (a) bad pixel, gaps, and reference data in the time-ordered normal data
    # (b) gaps and normal data in the time-ordered reference data
    # This "improves" upon the cosine interpolation performed above.

    # Parameters for the filter to be used.
    # length of apodization cosine filter
    elen = 110000 // (scipix_n + refpix_r + 2)
    # max unfiltered frequency
    blen = (512 + 512 // scipix_n * (refpix_r + 2) + pad) // \
           (scipix_n + refpix_r + 2) * ny // 2 - elen // 2

    # Construct the filter [1, cos, 0, cos, 1].

    temp_a1 = (np.cos(np.arange(elen, dtype=np.float32) *
                      np.pi / float(elen)) + 1.) / 2.

    # elen = 5000
    # blen = 30268
    # row * ny // 2 - 2 * blen - 2 * elen = 658552
    # len(temp_a2) = 729088

    temp_a2 = np.concatenate((np.ones(blen, dtype=np.float32),
                              temp_a1.copy(),
                              np.zeros(row * ny // 2 - 2 * blen - 2 * elen,
                                       dtype=np.float32),
                              temp_a1[::-1].copy(),
                              np.ones(blen, dtype=np.float32)))
    roll_a2 = np.roll(temp_a2, -1)
    aa = np.concatenate((temp_a2, roll_a2[::-1]))
    del temp_a1, temp_a2, roll_a2

    # IDL:  aa = a # replicate(1, s[3]) ; for application to the data
    # In IDL, aa is a 2-D array with one column of `a` for each group.  In
    # Python, numpy broadcasting should take care of this.

    n_iter_norm = 3
    dd0 = data0[0, :, :, :]
    # IDL:  fft_interp_norm, dd0, 2, replicate(1, s[1] / 4, s[2], 4),
    #                        row, hnorm, hnorm1, s, aa , n_iter_norm
    fft_interp_norm(dd0, np.ones((ny, nx // 4), dtype=np.int64),
                    row, hnorm, hnorm1,
                    ny, ngroups, aa, n_iter_norm)
    data0[0, :, :, :] = dd0.copy()
    del aa, dd0

#;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

#;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
    # The comments in this section are for scipix_n = 16, refpix_r = 4.
    # ; indices for keeping/shuffling reference pixels
    n0 = 512 // scipix_n
    n1 = scipix_n + refpix_r + 2
    ht = np.arange(n0 * n1, dtype=np.int32).reshape((n0, n1))   # (32, 22)
    ht[:, 0:(scipix_n - refpix_r) // 2 + 1] = -1
    ht[:, scipix_n // 2 + 1 + 3 * refpix_r // 2:] = -1
    hs = ht.copy()
    # ht is like href1, but extended over gaps and 1st and last norm pix.
    mask = (ht >= 0)
    ht = ht[mask]               # 1-D, length = 2 * refpix_r * 512 / scipix_n
    # IDL:  hs[scipix_n/2 + 1-refpix_r/2:scipix_n/2 + refpix_r + refpix_r/2,*]=hs[reform([transpose(reform(indgen(refpix_r),refpix_r/2,2)),transpose(reform(indgen(refpix_r),refpix_r/2,2))],refpix_r * 2) + scipix_n/2 + 1,*]  ; WIRED for R=2^(int)

    indr = np.arange(refpix_r, dtype=np.intp).reshape((2, refpix_r // 2))
    # indr_t =
    # [[0 2]
    #  [1 3]]
    indr_t = indr.transpose()
    # Before flattening, two_indr_t =
    # [[0 2 0 2]
    #  [1 3 1 3]]
    # After flattening, two_indr_t = [0 2 0 2 1 3 1 3].
    two_indr_t = np.concatenate((indr_t, indr_t), axis=1).flatten()
    two_indr_t += (scipix_n // 2 + 1)     # [9 11 9 11 10 12 10 12]
    hs[:, scipix_n // 2 + 1 - refpix_r // 2:
          scipix_n // 2 + 1 + refpix_r // 2 + refpix_r] = hs[:, two_indr_t]
    mask = (hs >= 0)
    hs = hs[mask]                       # hs is now 1-D

    if refpix_r % 4 == 2:
        len_hs = len(hs)
        temp_hs = hs.reshape(len_hs // 2, 2)
        temp_hs = temp_hs[:, ::-1]
        hs = temp_hs.flatten()

    # ; construct the reference data
    r0 = np.zeros_like(data0)
    r0[:, :, :, ht] = data0[:, :, :, hs]
    #;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

    # data0 has shape (5, ngroups, ny, row).  See the section above where
    # d0 was created, then copied (moved) to data0.
    shape_d = data0.shape
    # sd[1] = shape_d[3]   row (712)
    # sd[2] = shape_d[2]   ny (2048)
    # sd[3] = shape_d[1]   ngroups
    # sd[4] = shape_d[0]   5
    # s is used below, so for convenience, here are the values again:
    # s[1] = shape[2] = nx
    # s[2] = shape[1] = ny
    # s[3] = shape[0] = ngroups

    # IDL and numpy differ in where they apply the normalization for the
    # FFT.  This really shouldn't matter.
    normalization = float(shape_d[2] * shape_d[3])

    if beta is not None:
        # IDL:  refout0 = reform(data0[*,*,*,0], sd[1] * sd[2], sd[3])
        refout0 = data0[0, :, :, :].reshape((shape_d[1],
                                           shape_d[2] * shape_d[3]))
        # IDL:  refout0 = fft(refout0, dim=1, /over)
        # Divide by the length of the axis to be consistent with IDL.
        refout0 = np.fft.fft(refout0, axis=1) / normalization

    # IDL:  r0 = reform(r0, sd[1] * sd[2], sd[3], 5, /over)
    r0 = r0.reshape((5, shape_d[1], shape_d[2] * shape_d[3]))
    r0 = r0.astype(np.complex64)
    r0f = ["dummy", 1, 1, 1, 1]         # elements 1 - 4 populated in loop
    for k in range(1, 5):
        r0f[k] = np.fft.fft(r0[k, :, :], axis=1) / normalization

    # IDL:  for k=0,3 do oBridge[k]->Execute,
    #           "for i=0, s3-1 do r0[*,i] *= alpha"
    for k in range(1, 5):
        for i in range(ngroups):
            # Each element of r0f is the fft of r0[k, :, :], for some k.
            r0f[k][i, :] *= alpha[k - 1]

    # IDL:  for k=0,3 do oBridge[k]->Execute,
    #           "for i=0, s3-1 do r0[*,i] += beta * refout0[*,i]"
    if beta is not None:
        for k in range(1, 5):
            for i in range(ngroups):
                r0f[k][i, :] += (beta[k - 1] * refout0[i, :])

    # IDL:  for k=0,3 do oBridge[k]->Execute,
    #           "r0 = fft(r0, 1, dim=1, /overwrite)", /nowait
    for k in range(1, 5):
        r0[k, :, :] = np.fft.ifft(r0f[k], axis=1) * normalization

    # sd[1] = shape_d[3]   row (712)
    # sd[2] = shape_d[2]   ny (2048)
    # sd[3] = shape_d[1]   ngroups
    # sd[4] = shape_d[0]   5
    # IDL:  r0 = reform(r0, sd[1], sd[2], sd[3], 5, /over)
    r0 = r0.reshape(shape_d)
    r0 = r0.real
    r0 = r0[:, :, :, hnorm1]
    data0 = data0[:, :, :, hnorm1]

    data0 -= r0
    data0[2, :, :, :] = data0[2, :, :, ::-1]
    data0[4, :, :, :] = data0[4, :, :, ::-1]

    # IDL:  data0 = transpose(data0, [0,3,1,2])  0, 1, 2, 3 --> 0, 3, 1, 2
    # current order:  512, ny, ngroups, 5     (IDL)
    # current order:  5, ngroups, ny, 512     (numpy)
    #                 0  1        2   3       current numpy indices
    # transpose to:   512, 5, ny, ngroups     (IDL)
    # transpose to:   ngroups, ny, 5, 512     (numpy)
    #                 1        2   0  3       transpose order for numpy
    # Therefore:      0 1 2 3  -->  1 2 0 3   transpose order for numpy
    data0 = np.transpose(data0, (1, 2, 0, 3))

    # IDL:  data0 = reform(data0[*, 1:*, *, *], s[2], s[2], s[3], /over)
    # Note:  ny x ny, not ny x nx.
    data0 = data0[:, :, 1:, :].reshape((ngroups, ny, ny))
    # b_offset is the average over the ramp that we subtracted near the
    # beginning; add it back in.
    # Shape of b_offset is (2048, 3200), data0 is (ngroups, 2048, 2048).
    data0 += b_offset[..., irs2_mask]

    return data0

def fft_interp_norm(dd0, mask0, row, hnorm, hnorm1,
                    ny, ngroups, aa, n_iter_norm):

    mm = np.zeros((ny, row), dtype=np.int8)
    mm[:, hnorm1] = mask0[:, hnorm]
    hm = (mm != 0)                      # 2-D boolean mask
    for j in range(ngroups):
        dd = dd0[j, :, :].copy()
        p = dd.flatten()                        # make a copy, not a view
        for it in range(n_iter_norm):
            pp = np.fft.fft(p)
            pp *= aa
            p[:] = np.fft.ifft(pp).real
            p[hm.ravel()] = dd[hm]
        dd0[j, :, :] = p.reshape((ny, row))

def ols_line(x, y):
    """Fit a straight line using ordinary least squares."""

    xf = x.ravel()
    yf = y.ravel()
    if len(xf) < 1 or len(yf) < 1:
        return (0., 0.)

    groups = float(len(xf))

    mean_x = xf.mean()
    mean_y = yf.mean()
    sum_x2 = (xf**2).sum()
    sum_xy = (xf * yf).sum()

    slope = (sum_xy - groups * mean_x * mean_y) / \
            (sum_x2 - groups * mean_x**2)
    intercept = mean_y - slope * mean_x

    return (intercept, slope)
