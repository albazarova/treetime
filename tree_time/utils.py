import numpy as np
from scipy.interpolate import interp1d
import tree_time.tree_time.config as ttconf
from scipy.integrate import quad
from scipy import stats
import matplotlib.pyplot as plt

class DateConversion(object):
    """
    Small container class to store parameters to convert between branch length
    as it is used in ML computations and the dates of the nodes.
    It is assumed that the conversion formula is 'length = k*date + b'
    """
    def __init__(self):

        self.slope = 0
        self.intersept = 0
        self.r_val = 0
        self.pi_val = 0
        self.sigma = 0


    @classmethod
    def from_tree(cls, t):
        dc = cls()
        dates = []
        for node in t.find_clades():
            if hasattr(node, "raw_date" ) and node.raw_date is not None:
                dates.append((node.raw_date, node.dist2root))
        dates = np.array(dates)
        dc.slope,\
            dc.intersept,\
            dc.r_val,\
            dc.pi_val,\
            dc.sigma = stats.linregress(dates[:, 0], dates[:, 1])
        return dc

    def get_branch_len(self, date1, date2):
        """
        Compute branch length given the dates of the two nodes.

        Args:
         - date1 (int): date of the first node (days before present)
         - date2 (int): date of the second node (days before present)

        Returns:
         - branch length (double): Branch length, assuming that the dependence
         between the node date and the node depth in the the tree is linear.
        """
        return abs(date1 - date2) * self.slope

    def get_date(self, abs_t):
        """
        Get the approximate date of the tree node, assuming that the
        dependence between the node date and the node depth int the tree is
        linear.

        Args:
         - node(Phylo.Tree.Clade): node of the tree. Must be from the TreeAnc
         class (or its derivative), to contain the necessary attributes (
            dist2root).

        """
        days = abs_t / abs(self.slope)  #(self.intersept - abs_t) / self.slope
        if days < 0:
            print ("Warning: got the negative date! Returning the inverse.")
            days = abs(days)
        return days

def delta_fun(pos, return_log=True, normalized=False, width=ttconf.WIDTH_DELTA):
    """
    Create the interpolation object for delta function
    Args:

     - pos(double): position of the delta function maximum
     
     - return_log(bool): whether to return logarithm or pure delta-fun.
     
     - normalized(bool): If True, set the amplitude so that the integral of the 
     delta function is 1.

     - width(double): width of the delta function. 
    """        
    grid = np.concatenate(([ttconf.MIN_T],
        pos * np.array([1 - width,1 - width*0.5, 1 + width*0.5, 1 + width]),
        [ttconf.MAX_T]))
    if return_log:
        vals = np.array([
            ttconf.MIN_LOG,
            ttconf.MIN_LOG,
            0.0,
            0.0,#np.log(np.abs(pos/width)),
            ttconf.MIN_LOG,
            ttconf.MIN_LOG])
        if normalized:
            vals[2,3] = -np.log(width/1.5)
    else:
        vals = np.array([
            0.0,
            0.0,
            1.0,
            1.0,#np.log(np.abs(pos/width)),
            0.0,
            0.0])
        if normalized:
            vals[2,3] = 1.5 / width
    delta = interp1d(grid, -vals, kind='linear')
    delta.delta_pos=pos
    return delta

def min_interp(interp_object):
    """
    Find the global minimum of the interpolated function
    """
    return interp_object.x[interp_object(interp_object.x).argmin()]
    #opt_ = sciopt.minimize_scalar(interp_object,
    #    bounds=[-2 * self.max_diam, 2 * self.max_diam],
    #    method='brent')
    #return opt_.x
    #if opt_.success != True:
    #    return None

    #else:
    #    return opt_.x

def convolve(t, f, g, cutoff=100, n_integral=100):
    """
    Slow convolution algorithm

    f,g - logarithms!
    """

    # get the support ranges for the raw functions
    fx_min = f.x[(f.y - f.y.min()) < cutoff].min()
    fx_max = f.x[(f.y - f.y.min()) < cutoff].max()
    gx_min = g.x[(g.y - g.y.min()) < cutoff].min()
    gx_max = g.x[(g.y - g.y.min()) < cutoff].max()

    # resulting convolution
    res = np.zeros(t.shape[0])

    #def F(x,ti):
    #    return f(ti-x)*g(x)
    #
    for i, ti in enumerate(t):

        tau_min = np.max((ti-fx_max, gx_min))
        tau_max = np.min((ti-fx_min, gx_max))
        if (tau_min > tau_max):
            continue
        tau = np.linspace(tau_min, tau_max, n_integral)
        fg = np.exp(-1*(f(ti-tau) + g(tau)))
        res[i] = (0.5*(fg[1:]+fg[:-1])*(tau_max-tau_min)/n_integral).sum()
        # integrate f(t-tau)g(tau)dtau
        #res[i] = quad(F, 0, 1, args=(ti,))[0]

    res = -1*np.log(res)
    res[np.isinf (res)] = -1*ttconf.MIN_LOG
    res = interp1d(t, res, kind='linear')
    return res

def opt_branch_len(node):
    if not hasattr(node, "branch_neg_log_prob") or node.branch_neg_log_prob is None:
        return 0.0
    return min_interp(node.branch_neg_log_prob)

def find_node_opt_pos(node):
    if not hasattr(node, "msg_to_parent") or node.msg_to_parent is None:
        return None
    return min_interp(node.msg_to_parent)

def make_node_grid(opt, grid_size=ttconf.NODE_GRID_SIZE, variance=ttconf.NODE_GRID_VAR):
    # quadratic grid - fine around opt, sparse at the edges
    #grid_root = opt - scale * (np.linspace(1, 1e-5, grid_size / 3 - 1)**2)
    #grid_leaves = opt + scale * (np.linspace(0, 1, grid_size / 3)**2)
    grid_leaves = opt + ttconf.MAX_BRANCH_LENGTH * np.sign(np.linspace(-1, 1, grid_size))\
                        *(np.linspace(-1, 1, grid_size)**2)
    grid = np.concatenate(([ttconf.MIN_T],
        grid_leaves,
        [ttconf.MAX_T]))
    return grid

def multiply_dists(interps):
    """
    Multiply two distributions of inverse log-likelihoods,
    represented as interpolation objects. Takes array of interpolation objects,
    extracts the grid, builds the new grid for the resulting distribution,
    performs multiplication on a new grid.
    Args:

     - interps (iterable): Itarable of interpolation objects for -log(LH)
     distributions.

     - prefactors (iterable): scaling factors of hte distributions. Each
     distribution is (arbitrarly) scaled so that the max value is 1, hence
     min(-log(LH(x))) = 0. The prefactors will be summed, the new prefactor
     will be added and the result will be returned as the prefactor for the
     resulting distribution

     - grid_size (int, default 100): The number of nodes in the interpolation
     object X-scale.

    Returns:
     - interp: Resulting interpolation object for the -log(LH) distribution

     - pre(double): distribution pre-factor
    """

    #prefactor = np.sum(prefactors)
    grid_size = ttconf.NODE_GRID_SIZE
    min_grid_size = np.min([len(k.x) for k in interps])
    # correction for delta-functions distribution of terminal nodes
    if min_grid_size < 10: # just combine the two grids
        grid = np.concatenate([k.x for k in interps])
        grid = np.unique(grid) # exclude repetitive points (terminals)
    else: # create new grid from combination of two

        opts = [min_interp(k) for k in interps]
        opts = [k for k in opts if k is not None]
        grid = np.unique(np.concatenate ((opts, make_node_grid(np.mean(opts)))))

    node_prob = np.sum([k(grid) for k in interps], axis=0)

    node_prob[((0,-1),)] = -1 * ttconf.MIN_LOG # +1000
    node_prob[((1,-2),)] = -1 * ttconf.MIN_LOG / 2 # +500

    interp = interp1d(grid, node_prob, kind='linear')
    return interp

if __name__ == '__main__':
    pass
