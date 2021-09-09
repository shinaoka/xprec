import numpy as np
from warnings import warn

from . import array
from . import _dd_linalg

norm = _dd_linalg.norm
givens = _dd_linalg.givens
svd_tri2x2 = _dd_linalg.svd_tri2x2
svvals_tri2x2 = _dd_linalg.svvals_tri2x2
householder = _dd_linalg.householder
mul_givens = _dd_linalg.mul_givens


def householder_vector(x):
    return householder(array.asddarray(x))


def householder_update(A, Q):
    beta, v = householder_vector(A[:,0])
    w = beta * (A.T @ v)
    A -= v[:,None] * w[None,:]
    Q[0,0] = beta
    Q[1:,0] = v[1:]


def householder_bidiag(A):
    A = np.array(A, copy=True, subok=True)

    m, n = A.shape
    if m < n:
        raise NotImplementedError("must be tall matrix")

    rq = n - (m == n)
    Q = np.zeros_like(A)
    R = np.zeros_like(A[:n,:n])

    for j in range(n-2):
        householder_update(A[j:,j:], Q[j:,j:])
        householder_update(A[j:,j+1:].T, R[j+1:,j+1:])
    for j in range(n-2, rq):
        householder_update(A[j:,j:], Q[j:,j:])
    return Q, A, R


def householder_apply(H, Q):
    H = np.asanyarray(H)
    Q = Q.copy()
    m, r = H.shape
    if Q.shape != (m, m):
        raise ValueError("invalid shape")
    for j in range(r-1, -1, -1):
        beta = H[j,j]
        if np.equal(beta, 0):
            continue
        v = np.empty_like(H[j:,0])
        v[0] = 1
        v[1:] = H[j+1:,j]
        Qpart = Q[j:,j:]
        w = beta * (Qpart.T @ v)
        Qpart -= v[:,None] * w[None,:]
    return Q


def givens_apply_left(k, q, G, A):
    """Apply givens rotation `G` to a matrix `A` from the left: `G @ A`"""
    mul_givens([k, q], G, A, out=A)


def givens_apply_right(k, q, G, A):
    """Apply givens rotation `G` to a matrix `A` from the left: `A @ G`"""
    mul_givens([k, q], G.T, A.T, out=A.T)


def golub_kahan_chase(d, e, shift):
    n = d.size
    G_V = []
    G_U = []

    f = (np.abs(d[0]) - shift) * (np.copysign(1.0, d[0]) + shift / d[0])
    g = e[0]

    for i in range(n-1):
        r, G = givens(array.ddarray([f, g]))
        cosr, sinr = G[0]
        if i > 0:
            e[i-1] = r[0]
        f = cosr * d[i] + sinr * e[i]
        e[i] = cosr * e[i] - sinr * d[i]
        g = sinr * d[i+1]
        d[i+1] = cosr * d[i+1]
        G_V.append(G)

        r, G = givens(array.ddarray([f, g]))
        cosl, sinl = G[0]
        d[i] = r[0]
        f = cosl * e[i] + sinl * d[i+1]
        d[i+1] = cosl * d[i+1] - sinl * e[i]
        if i < n-2:
            g = sinl * e[i+1]
            e[i+1] = cosl * e[i+1]
        G_U.append(G)

    e[n-2] = f
    return array.ddarray(G_U), array.ddarray(G_V)


def svd_apply_givens(G_V, VT):
    indices = np.array([0, 1])
    for G in G_V:
        mul_givens(indices, G, VT, out=VT)
        indices += 1


def estimate_sbounds(d, f):
    abs_d = np.abs(d)
    abs_f = np.abs(f)
    n = abs_d.size

    def iter_backward():
        lambda_ = abs_d[n-1]
        yield lambda_
        for j in range(n-2, -1, -1):
            lambda_ = abs_d[j] * (lambda_ / (lambda_ + abs_f[j]))
            yield lambda_

    def iter_forward():
        mu = abs_d[0]
        yield mu
        for j in range(n-1):
            mu = abs_d[j+1] * (mu / (mu + abs_f[j]))
            yield mu

    smin = min(min(iter_backward()), min(iter_forward()))
    smax = max(max(abs_d), max(abs_f))
    return smax, smin


def golub_kahan_svd(d, f, U, VH, max_iter=30, step=golub_kahan_chase):
    n = d.size
    n1 = 0
    n2 = n-1
    count = 0

    # See LAWN3 page 6 and 22
    _, sigma_minus = estimate_sbounds(d, f)
    tol = 100 * 5e-32
    thresh = tol * sigma_minus

    for i_iter in range(max_iter):
        # Search for biggest index for non-zero off diagonal value in e
        for n2i in range(n2, 0, -1):
            if abs(f[n2i-1]) > thresh:
                n2 = n2i
                break
        else:
            return

        # Search for largest sub-bidiagonal matrix ending at n2
        for _n1 in range(n2 - 1, -1, -1):
            if abs(f[_n1]) < thresh:
                n1 = _n1
                break
        else:
            n1 = 0

        #print("iter={}, range={}:{}".format(i_iter, n1, n2+1))

        # TODO CHECK THIS!
        if n1 == n2:
            return

        tail = array.ddarray([d[n2-1],   f[n2-1],
                              0 * d[n2], d[n2]]).reshape(2, 2)
        shift = svvals_tri2x2(tail)[1]
        G_U, G_V = step(d[n1:n2+1], f[n1:n2], shift)
        svd_apply_givens(G_V, VH[n1:n2+1, :])
        svd_apply_givens(G_U, U[:, n1:n2+1].T)
    else:
        warn("Did not converge!")


def svd(A):
    m, n = A.shape
    U, B, V = householder_bidiag(A)
    U = householder_apply(U, array.ddarray(np.eye(m)))
    V = householder_apply(V, array.ddarray(np.eye(n)))
    VT = V.T

    d = B.diagonal().copy()
    f = B.diagonal(1).copy()
    golub_kahan_svd(d, f, U, VT, 1000)
    return U, d, VT
